#!/usr/bin/env python3
"""
Hanazeder HLC-20 → MQTT bridge
Verbindet per TCP mit dem Silex SX2000U Seriell-Server und
veröffentlicht alle Sensorwerte via MQTT mit Home Assistant Auto-Discovery.

Protokoll-Referenz: https://github.com/binderth/serial_hlc20
Moduladressen: aus .hlc-PRE-Byte-Analyse + live verifiziert (2026-08-21)
"""

import json
import logging
import os
import signal
import sys
import time

import paho.mqtt.client as mqtt
import serial

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("hlc20_mqtt")

# ─── Konfiguration aus Umgebungsvariablen ─────────────────────────────────────
SILEX_HOST       = os.environ["SILEX_HOST"]
SILEX_PORT       = int(os.getenv("SILEX_PORT", "10001"))
MQTT_HOST        = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT        = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER        = os.getenv("MQTT_USER", "")
MQTT_PASSWORD    = os.getenv("MQTT_PASSWORD", "")
POLL_INTERVAL    = int(os.getenv("POLL_INTERVAL", "60"))
DEVICE_TOPIC     = os.getenv("DEVICE_TOPIC", "hlc20")
DISCOVERY_PREFIX = os.getenv("DISCOVERY_PREFIX", "homeassistant")

BAUD_RATE        = 38400
READ_DELAY       = 0.15   # Sekunden zwischen Senden und Lesen

# ─── Sensor-Definitionen ──────────────────────────────────────────────────────
# Moduladressen aus .hlc-Datei PRE-Byte-Analyse + live Verifikation gegen Display.
# kind:      "temp" → Temperatursensor (°C), "pump" → Pumpe (AN/AUS)
# error_raw: Rohdaten die Sensor-Fehler bedeuten → kein Publish
SENSORS = [
    # Puffer
    {"id": "puff_oben",     "label": "Puff oben",       "mod": 3,   "kind": "temp", "error_raw": []},
    {"id": "puff_mitte",    "label": "Puff mitte",      "mod": 1,   "kind": "temp", "error_raw": []},
    {"id": "puff_unten",    "label": "Puff unten",      "mod": 12,  "kind": "temp", "error_raw": []},
    # Solar
    {"id": "sol_kollektor", "label": "Sol-Kollektor",   "mod": 69,  "kind": "temp", "error_raw": [4000]},
    {"id": "vorl_solar",    "label": "Vorl-Solar",      "mod": 80,  "kind": "temp", "error_raw": []},
    {"id": "rueckl_solar",  "label": "Rückl-Solar",     "mod": 81,  "kind": "temp", "error_raw": []},
    # Heizkreise
    {"id": "vl_ist_hk",     "label": "VL ist HK",       "mod": 45,  "kind": "temp", "error_raw": []},
    {"id": "vl_soll_hk",    "label": "VL soll HK",      "mod": 28,  "kind": "temp", "error_raw": []},
    {"id": "vl_ist_fbh",    "label": "VL ist FBH",      "mod": 152, "kind": "temp", "error_raw": []},
    {"id": "vl_soll_fbh",   "label": "VL soll FBH",     "mod": 143, "kind": "temp", "error_raw": []},
    # Weitere Sensoren
    {"id": "aussenfuehler", "label": "Außenfühler",     "mod": 33,  "kind": "temp", "error_raw": []},
    {"id": "fuhl_zirku_bw", "label": "Fühl-Zirku-BW",  "mod": 86,  "kind": "temp", "error_raw": []},
    {"id": "raum_temp",     "label": "Raum-Temp",       "mod": 173, "kind": "temp", "error_raw": [1800]},
    # Pumpen (val > 0 → AN)
    {"id": "pumpe_solar",   "label": "Pumpe Solar",     "mod": 75,  "kind": "pump", "error_raw": []},
    {"id": "pumpe_hk",      "label": "Pumpe HK",        "mod": 46,  "kind": "pump", "error_raw": []},
    {"id": "pumpe_fbh",     "label": "Pumpe FBH",       "mod": 153, "kind": "pump", "error_raw": []},
    {"id": "pumpe_zirk",    "label": "Pumpe Zirk",      "mod": 83,  "kind": "pump", "error_raw": []},
    {"id": "pumpe_kessel",  "label": "Pumpe Kessel",    "mod": 8,   "kind": "pump", "error_raw": []},
]

DEVICE_INFO = {
    "identifiers":  ["hanazeder_hlc20"],
    "name":         "Hanazeder HLC-20",
    "model":        "HLC-20",
    "manufacturer": "Hanazeder",
}


# ─── HLC-20-Protokoll ─────────────────────────────────────────────────────────

def hlc_open() -> serial.Serial:
    """Öffnet TCP-Verbindung zum Silex und führt HLC-Handshake durch."""
    url = f"socket://{SILEX_HOST}:{SILEX_PORT}"
    log.info("Verbinde mit Silex: %s", url)
    ser = serial.serial_for_url(url, baudrate=BAUD_RATE, timeout=0.5)
    ser.write(bytes.fromhex("953073"))
    time.sleep(1.0)
    resp = ser.read(64)
    if resp:
        log.info("Handshake OK: %s", resp.hex(" ").upper())
    else:
        log.warning("Kein Handshake-Echo – weiter trotzdem")
    return ser


def hlc_read(ser: serial.Serial, mod: int) -> int | None:
    """Liest Modul `mod` (F1, Index 0). Gibt rohen 16-bit-Signed-Wert zurück."""
    cmd = bytes([0x98, 0x00, mod, 0xF1, 0x00])
    ser.write(cmd)
    time.sleep(READ_DELAY)
    resp = ser.read(64)
    if not resp or len(resp) < 3:
        return None
    raw = (resp[1] << 8) | resp[2]
    return raw - 65536 if raw > 32767 else raw


# ─── MQTT Auto-Discovery ──────────────────────────────────────────────────────

def publish_discovery(client: mqtt.Client) -> None:
    """Veröffentlicht MQTT Auto-Discovery-Konfigurationen für HA."""
    for s in SENSORS:
        sid   = s["id"]
        label = s["label"]
        kind  = s["kind"]

        if kind == "temp":
            ha_type    = "sensor"
            state_topic = f"{DEVICE_TOPIC}/{ha_type}/{sid}"
            config = {
                "name":                label,
                "unique_id":           f"hlc20_{sid}",
                "state_topic":         state_topic,
                "unit_of_measurement": "°C",
                "device_class":        "temperature",
                "state_class":         "measurement",
                "device":              DEVICE_INFO,
            }
        else:  # pump
            ha_type    = "binary_sensor"
            state_topic = f"{DEVICE_TOPIC}/{ha_type}/{sid}"
            config = {
                "name":       label,
                "unique_id":  f"hlc20_{sid}",
                "state_topic": state_topic,
                "device_class": "running",
                "payload_on":  "ON",
                "payload_off": "OFF",
                "device":     DEVICE_INFO,
            }

        discovery_topic = f"{DISCOVERY_PREFIX}/{ha_type}/hlc20_{sid}/config"
        client.publish(discovery_topic, json.dumps(config), retain=True)
        log.debug("Discovery: %s", discovery_topic)

    log.info("MQTT Auto-Discovery für %d Sensoren veröffentlicht", len(SENSORS))


# ─── Polling-Schleife ─────────────────────────────────────────────────────────

def poll_and_publish(ser: serial.Serial, client: mqtt.Client) -> int:
    """Liest alle Sensoren und publisht die Werte. Gibt Anzahl Fehler zurück."""
    errors = 0
    for s in SENSORS:
        try:
            raw = hlc_read(ser, s["mod"])
        except Exception as exc:
            log.error("Lesefehler %s: %s", s["id"], exc)
            errors += 1
            continue

        if raw is None:
            log.warning("Keine Antwort: %s (Mod %d)", s["id"], s["mod"])
            errors += 1
            continue

        if raw in s["error_raw"]:
            log.debug("Sensor-Fehler ignoriert: %s raw=%d", s["id"], raw)
            continue

        if s["kind"] == "temp":
            value = round(raw / 10.0, 1)
            topic = f"{DEVICE_TOPIC}/sensor/{s['id']}"
            client.publish(topic, str(value))
            log.debug("%-20s %.1f °C", s["id"], value)
        else:
            state = "ON" if raw > 0 else "OFF"
            topic = f"{DEVICE_TOPIC}/binary_sensor/{s['id']}"
            client.publish(topic, state)
            log.debug("%-20s %s (raw=%d)", s["id"], state, raw)

    return errors


# ─── Hauptschleife ────────────────────────────────────────────────────────────

def build_mqtt_client() -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="hlc20_bridge")
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
    client.will_set(f"{DEVICE_TOPIC}/status", "offline", retain=True)
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()
    return client


def main() -> None:
    shutdown = False

    def _on_signal(sig, _frame):
        nonlocal shutdown
        log.info("Signal %d – beende...", sig)
        shutdown = True

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT,  _on_signal)

    log.info("HLC-20 MQTT Bridge startet (Polling alle %ds)", POLL_INTERVAL)
    log.info("Silex: %s:%d  MQTT: %s:%d", SILEX_HOST, SILEX_PORT, MQTT_HOST, MQTT_PORT)

    client = build_mqtt_client()
    client.publish(f"{DEVICE_TOPIC}/status", "online", retain=True)
    publish_discovery(client)

    ser: serial.Serial | None = None

    while not shutdown:
        # Serielle Verbindung aufbauen / wiederherstellen
        if ser is None or not ser.is_open:
            try:
                if ser is not None:
                    try:
                        ser.close()
                    except Exception:
                        pass
                ser = hlc_open()
            except Exception as exc:
                log.error("Verbindung zu Silex fehlgeschlagen: %s – Retry in 30s", exc)
                time.sleep(30)
                continue

        try:
            errors = poll_and_publish(ser, client)
            log.info("Poll abgeschlossen – %d Sensoren, %d Fehler",
                     len(SENSORS), errors)
            if errors > len(SENSORS) // 2:
                # Zu viele Fehler → Verbindung neu aufbauen
                log.warning("Zu viele Fehler – Serielle Verbindung wird neu aufgebaut")
                ser.close()
                ser = None
        except Exception as exc:
            log.error("Unerwarteter Fehler beim Polling: %s", exc)
            try:
                ser.close()
            except Exception:
                pass
            ser = None

        # Warte bis zum nächsten Poll-Zyklus
        deadline = time.monotonic() + POLL_INTERVAL
        while not shutdown and time.monotonic() < deadline:
            time.sleep(1)

    # Sauberes Beenden
    client.publish(f"{DEVICE_TOPIC}/status", "offline", retain=True)
    client.loop_stop()
    client.disconnect()
    if ser and ser.is_open:
        ser.close()
    log.info("Bridge beendet.")


if __name__ == "__main__":
    main()
