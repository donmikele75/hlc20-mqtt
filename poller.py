"""Background thread: poll HLC-20 via serial, publish to MQTT, run bus scans."""
import json
import logging
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import serial

from config import Config
from mixer import MixerAxis
from protocol import hlc_open, hlc_read, hlc_read_param
from state import AppState

log = logging.getLogger("hlc20.poller")

_DEVICE_INFO = {
    "identifiers":  ["hanazeder_hlc20"],
    "name":         "Hanazeder HLC-20",
    "model":        "HLC-20",
    "manufacturer": "Hanazeder",
}


def _to_hex(raw: int) -> str:
    u = raw if raw >= 0 else raw + 65536
    return f"{u & 0xFF:02X} {(u >> 8) & 0xFF:02X}"


class PollerThread(threading.Thread):
    def __init__(self, state: AppState, cfg_ref: list) -> None:
        super().__init__(daemon=True, name="poller")
        self.state = state
        self.cfg_ref = cfg_ref          # mutable [Config] — web routes replace cfg_ref[0]
        self._stop = threading.Event()
        self._reload = threading.Event()
        self._ser: serial.Serial | None = None
        self._mqtt: mqtt.Client | None = None
        # Modulnummern aus .hlc-Analyse verifiziert; nur lesende Zustandsschaetzung
        self._mixer_hk = MixerAxis(zu_mod=50, auf_mod=51)
        self._mixer_fbh = MixerAxis(zu_mod=157, auf_mod=158)

    @property
    def _cfg(self) -> Config:
        return self.cfg_ref[0]

    def request_reload(self) -> None:
        self._reload.set()

    def stop(self) -> None:
        self._stop.set()

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        while not self._stop.is_set():
            if self._reload.is_set():
                self._reload.clear()
                self._open_serial()
                self._open_mqtt()

            if self._ser is None or not self._ser.is_open:
                self._open_serial()
                if self._ser is None:
                    self._stop.wait(30)
                    continue

            if self._mqtt is None:
                self._open_mqtt()

            if self.state.scan_requested.is_set():
                self.state.scan_requested.clear()
                self._scan()
                continue

            try:
                errors = self._poll()
                ts = datetime.now(timezone.utc).isoformat()
                self.state.last_poll_ts = ts
                self.state.last_poll_errors = errors
                self.state.emit({
                    "type": "poll_complete", "ts": ts, "errors": errors,
                    "serial": self.state.serial_connected,
                    "mqtt":   self.state.mqtt_connected,
                })
                log.info("Poll: %d Sensoren + %d Parameter, %d Fehler",
                         len(self._cfg.sensors), len(self._cfg.params), errors)
            except Exception as exc:
                log.error("Poll-Ausnahme: %s", exc)
                self._close_serial()
                continue

            # Wait for next cycle, bail early on scan/reload/stop.
            # Read-only Mischer-Substatusabfrage in konfigurierbarem Takt einschieben.
            deadline = time.monotonic() + self._cfg.poll_interval
            next_mixer = time.monotonic()
            while not self._stop.is_set() and time.monotonic() < deadline:
                if self.state.scan_requested.is_set() or self._reload.is_set():
                    break
                now = time.monotonic()
                if now >= next_mixer and self._ser is not None and self._ser.is_open:
                    try:
                        self._poll_mixers()
                    except Exception as exc:
                        log.error("Mischer-Poll-Ausnahme: %s", exc)
                        self._close_serial()
                        break
                    next_mixer = time.monotonic() + max(0.5, self._cfg.mixer_poll_interval)
                self._stop.wait(max(0.2, min(0.5, self._cfg.mixer_poll_interval)))

        self._close_serial()
        self._close_mqtt()
        log.info("Poller beendet")

    # ── Poll one cycle ────────────────────────────────────────────────────────

    def _poll(self) -> int:
        errors = 0
        ts = datetime.now(timezone.utc).isoformat()
        sensors = list(self._cfg.sensors)   # snapshot to avoid mutation races
        params  = list(self._cfg.params)
        cfg = self._cfg

        for s in sensors:
            sid = s["id"]
            try:
                raw = hlc_read(self._ser, s["mod"])
            except Exception as exc:
                log.error("Lesefehler %s: %s", sid, exc)
                errors += 1
                self._close_serial()
                raise

            if raw is None:
                log.warning("Keine Antwort: %s (Mod %d)", sid, s["mod"])
                errors += 1
                continue

            if raw in s.get("error_raw", []):
                continue

            kind = s.get("kind", "temp")
            if kind == "temp":
                value_str = str(round(raw / 10.0, 1))
                if self._mqtt:
                    self._mqtt.publish(f"{cfg.device_topic}/sensor/{sid}", value_str)
            else:
                value_str = "ON" if raw > 0 else "OFF"
                if self._mqtt:
                    self._mqtt.publish(f"{cfg.device_topic}/binary_sensor/{sid}", value_str)

            entry = {
                "id": sid, "label": s["label"], "value": value_str,
                "unit": "°C" if kind == "temp" else "",
                "kind": kind, "raw": raw, "hex": _to_hex(raw),
                "mod": s["mod"], "ts": ts,
            }
            self.state.current_values[sid] = entry
            self.state.emit({"type": "update", **entry})

        for p in params:
            pid = p["id"]
            try:
                raw = hlc_read_param(self._ser, p["mod"], p["idx"])
            except Exception as exc:
                log.error("Lesefehler Param %s: %s", pid, exc)
                errors += 1
                self._close_serial()
                raise

            if raw is None:
                log.warning("Keine Antwort: %s (Mod %d Idx %d)", pid, p["mod"], p["idx"])
                errors += 1
                continue

            value_str = str(round(raw / 10.0, 1))
            if self._mqtt:
                self._mqtt.publish(f"{cfg.device_topic}/sensor/{pid}", value_str)

            entry = {
                "id": pid, "label": p["label"], "value": value_str,
                "unit": p.get("unit", "°C"), "kind": "param",
                "raw": raw, "hex": _to_hex(raw),
                "mod": p["mod"], "idx": p.get("idx", 0), "ts": ts,
            }
            self.state.current_values[pid] = entry
            self.state.emit({"type": "update", **entry})

        return errors

    # ── Mischer-Positionsschaetzung (read-only) ──────────────────────────────

    def _poll_mixers(self) -> None:
        cfg = self._cfg
        now = time.monotonic()
        ts = datetime.now(timezone.utc).isoformat()
        for axis, sid, label in (
            (self._mixer_hk,  "mischer_hk_position",  "Mischer HK Position (geschätzt)"),
            (self._mixer_fbh, "mischer_fbh_position", "Mischer FBH Position (geschätzt)"),
        ):
            zu_raw = hlc_read(self._ser, axis.zu_mod)
            auf_raw = hlc_read(self._ser, axis.auf_mod)
            if zu_raw is None or auf_raw is None:
                continue
            axis.update(zu_raw > 0, auf_raw > 0, cfg.mixer_runtime_s, now)

            calibrated = axis.position is not None
            value_str = f"{axis.position:.0f}" if calibrated else "unkalibriert"
            if self._mqtt and calibrated:
                self._mqtt.publish(f"{cfg.device_topic}/sensor/{sid}", value_str)

            entry = {
                "id": sid, "label": label, "value": value_str,
                "unit": "%" if calibrated else "", "kind": "mixer_position",
                "raw": None, "hex": "", "mod": axis.zu_mod,
                "direction": axis.direction, "calibrated": calibrated, "ts": ts,
            }
            self.state.current_values[sid] = entry
            self.state.emit({"type": "update", **entry})

    # ── Bus scan ──────────────────────────────────────────────────────────────

    def _scan(self) -> None:
        log.info("Bus-Scan gestartet")
        self.state.emit({"type": "scan_started"})

        known: dict[int, str] = {}
        for s in self._cfg.sensors:
            known[s["mod"]] = s["label"]
        for p in self._cfg.params:
            known.setdefault(p["mod"], p["label"])

        ts = datetime.now(timezone.utc).isoformat()
        for mod in range(256):
            if self.state.scan_stop.is_set():
                self.state.scan_stop.clear()
                self.state.emit({"type": "scan_stopped", "mod": mod})
                log.info("Scan abgebrochen bei Mod %d", mod)
                return

            try:
                raw = hlc_read(self._ser, mod)
            except Exception as exc:
                log.error("Scan-Lesefehler Mod %d: %s", mod, exc)
                raw = None

            self.state.emit({
                "type":      "scan_result",
                "mod":       mod,
                "raw":       raw,
                "hex":       _to_hex(raw) if raw is not None else "--",
                "value":     round(raw / 10.0, 1) if raw is not None else None,
                "has_value": raw is not None,
                "label":     known.get(mod, ""),
                "pct":       round(mod / 255 * 100),
                "ts":        ts,
            })

        self.state.emit({"type": "scan_complete", "ts": ts})
        log.info("Bus-Scan abgeschlossen: 256 Module geprüft")

    # ── Serial helpers ────────────────────────────────────────────────────────

    def _open_serial(self) -> None:
        self._close_serial()
        if not self._cfg.serial_host:
            return
        try:
            ser, echo = hlc_open(self._cfg.serial_host, self._cfg.serial_port)
            self._ser = ser
            self.state.serial_connected = True
            self.state.emit({"type": "status", "serial_connected": True,
                             "echo": echo or ""})
            log.info("Serial verbunden%s", f" – Echo: {echo}" if echo else "")
        except Exception as exc:
            log.error("Serial-Verbindung fehlgeschlagen: %s", exc)
            self.state.serial_connected = False
            self.state.emit({"type": "status", "serial_connected": False})

    def _close_serial(self) -> None:
        if self._ser:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None
        self.state.serial_connected = False

    # ── MQTT helpers ──────────────────────────────────────────────────────────

    def _open_mqtt(self) -> None:
        self._close_mqtt()
        cfg = self._cfg
        if not cfg.mqtt_host:
            return
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="hlc20_bridge")
            if cfg.mqtt_user:
                client.username_pw_set(cfg.mqtt_user, cfg.mqtt_password)
            client.will_set(f"{cfg.device_topic}/status", "offline", retain=True)
            client.connect(cfg.mqtt_host, cfg.mqtt_port, keepalive=60)
            client.loop_start()
            client.publish(f"{cfg.device_topic}/status", "online", retain=True)
            self._mqtt = client
            self.state.mqtt_connected = True
            self.state.emit({"type": "status", "mqtt_connected": True})
            self._publish_discovery(client)
            log.info("MQTT verbunden: %s:%d", cfg.mqtt_host, cfg.mqtt_port)
        except Exception as exc:
            log.error("MQTT-Verbindung fehlgeschlagen: %s", exc)
            self.state.mqtt_connected = False
            self.state.emit({"type": "status", "mqtt_connected": False})

    def _close_mqtt(self) -> None:
        if self._mqtt:
            try:
                self._mqtt.publish(f"{self._cfg.device_topic}/status", "offline", retain=True)
                self._mqtt.loop_stop()
                self._mqtt.disconnect()
            except Exception:
                pass
            self._mqtt = None
        self.state.mqtt_connected = False

    def _publish_discovery(self, client: mqtt.Client) -> None:
        cfg = self._cfg
        for s in cfg.sensors:
            sid, label, kind = s["id"], s["label"], s.get("kind", "temp")
            if kind == "temp":
                disc = {
                    "name": label, "unique_id": f"hlc20_{sid}",
                    "state_topic": f"{cfg.device_topic}/sensor/{sid}",
                    "unit_of_measurement": "°C", "device_class": "temperature",
                    "state_class": "measurement", "device": _DEVICE_INFO,
                }
                client.publish(
                    f"{cfg.discovery_prefix}/sensor/hlc20_{sid}/config",
                    json.dumps(disc), retain=True)
            else:
                disc = {
                    "name": label, "unique_id": f"hlc20_{sid}",
                    "state_topic": f"{cfg.device_topic}/binary_sensor/{sid}",
                    "device_class": "running",
                    "payload_on": "ON", "payload_off": "OFF",
                    "device": _DEVICE_INFO,
                }
                client.publish(
                    f"{cfg.discovery_prefix}/binary_sensor/hlc20_{sid}/config",
                    json.dumps(disc), retain=True)

        for p in cfg.params:
            pid, unit = p["id"], p.get("unit", "°C")
            disc: dict = {
                "name": p["label"], "unique_id": f"hlc20_{pid}",
                "state_topic": f"{cfg.device_topic}/sensor/{pid}",
                "state_class": "measurement", "device": _DEVICE_INFO,
            }
            if unit == "°C":
                disc["unit_of_measurement"] = "°C"
                disc["device_class"] = "temperature"
            elif unit:
                disc["unit_of_measurement"] = unit
            client.publish(
                f"{cfg.discovery_prefix}/sensor/hlc20_{pid}/config",
                json.dumps(disc), retain=True)

        # Mischer-Positionsschaetzung: nur Prozentwert, kein device_class (kein Standard-Sensortyp)
        for sid, label in (("mischer_hk_position", "Mischer HK Position (geschätzt)"),
                           ("mischer_fbh_position", "Mischer FBH Position (geschätzt)")):
            disc = {
                "name": label, "unique_id": f"hlc20_{sid}",
                "state_topic": f"{cfg.device_topic}/sensor/{sid}",
                "unit_of_measurement": "%", "device": _DEVICE_INFO,
            }
            client.publish(
                f"{cfg.discovery_prefix}/sensor/hlc20_{sid}/config",
                json.dumps(disc), retain=True)
