"""Empirische Wochenschaltuhr-Rekonstruktion aus beobachteten Tag/Nacht-Flanken.

Die Steuerung liefert kein Lesekommando fuer die komplette Wochenschaltuhr
(siehe /memories/repo/hlc20-mqtt-protocol.md fuer die Analyse). Stattdessen
wird der bereits gepollte Live-Status ("kind": "status", z.B. hk_tagbetrieb,
Modul 42 Typ 0xF1) beobachtet: bei jedem 0->1/1->0-Uebergang werden Wochentag
und Uhrzeit notiert. Nach spaetestens einer vollen Woche ergibt sich daraus
die Start-/Endzeit je Wochentag.
"""
import json
import logging
import os
import threading
from datetime import datetime

log = logging.getLogger("hlc20.schedule_log")

_HERE = os.path.dirname(os.path.abspath(__file__))
SCHEDULE_LOG_PATH = os.getenv("SCHEDULE_LOG_PATH", os.path.join(_HERE, "data", "schedule_log.json"))

DAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


class ScheduleLogger:
    """Rekonstruiert Wochenschaltuhr-Fenster aus beobachteten Statuswechseln."""

    def __init__(self, path: str = SCHEDULE_LOG_PATH) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._data: dict = self._load()

    def _load(self) -> dict:
        if os.path.exists(self._path):
            try:
                with open(self._path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                log.warning("schedule_log.json fehlerhaft, starte leer: %s", exc)
        return {}

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def update(self, key: str, active: bool, ts: datetime) -> None:
        """Bei jeder gepollten Statusaenderung aufrufen (ts = lokale Wanduhrzeit)."""
        with self._lock:
            entry = self._data.setdefault(key, {"last_state": None, "pending": None, "days": {}})
            prev = entry.get("last_state")
            entry["last_state"] = active
            if prev is None or prev == active:
                self._save()
                return
            if active:
                # 0 -> 1: neues Fenster beginnt
                entry["pending"] = {"day": DAYS[ts.weekday()], "start": ts.strftime("%H:%M")}
            else:
                # 1 -> 0: offenes Fenster schliessen (haengt am Start-Wochentag, nicht am Off-Zeitpunkt)
                pending = entry.pop("pending", None)
                if pending:
                    end = "24:00" if ts.strftime("%H:%M") == "00:00" else ts.strftime("%H:%M")
                    entry["days"][pending["day"]] = {
                        "start": pending["start"],
                        "end": end,
                        "updated": ts.isoformat(timespec="seconds"),
                    }
            self._save()

    def snapshot(self) -> dict:
        """Tiefe Kopie des aktuellen Stands (threadsicher lesbar)."""
        with self._lock:
            return json.loads(json.dumps(self._data))


schedule_logger = ScheduleLogger()
