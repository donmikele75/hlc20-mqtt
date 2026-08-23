"""Anwendungs-Log: persistente Rotating-Logdatei + Tail-Zugriff fuer Diagnose per API."""
import logging
import logging.handlers
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.getenv("LOG_PATH", os.path.join(_HERE, "data", "app.log"))

_file_handler: logging.handlers.TimedRotatingFileHandler | None = None


def setup(retention_days: int = 14, level: str = "INFO") -> None:
    """Root-Logger mit Konsole + rotierender Datei (persistiert unter /app/data) einrichten."""
    global _file_handler
    root = logging.getLogger()
    root.setLevel(logging.getLevelName(level))

    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
                             datefmt="%Y-%m-%d %H:%M:%S")

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    # Logdatei ist ein Best-effort-Feature (Diagnose per /api/logs) - ein Problem mit
    # dem gemounteten /app/data (Rechte, Netzwerk-Share o.ae.) darf den App-Start nicht crashen.
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        _file_handler = logging.handlers.TimedRotatingFileHandler(
            LOG_PATH, when="midnight", backupCount=max(1, retention_days), encoding="utf-8")
        _file_handler.setFormatter(fmt)
        root.addHandler(_file_handler)
    except OSError as exc:
        root.warning("Log-Datei (%s) nicht beschreibbar, nur Konsole aktiv: %s", LOG_PATH, exc)


def set_retention_days(days: int) -> None:
    """Aufbewahrungsdauer nachtraeglich anpassen (z.B. nach Einstellungen-Speichern)."""
    if _file_handler is not None:
        _file_handler.backupCount = max(1, days)


def set_level(level: str) -> None:
    """Log-Level nachtraeglich anpassen (z.B. auf DEBUG fuer einzelne Sensor-Reads)."""
    logging.getLogger().setLevel(logging.getLevelName(level))


def tail(n: int = 300) -> list[str]:
    """Letzte n Zeilen der aktuellen Logdatei (nur die aktive, keine rotierten Archive)."""
    if not os.path.exists(LOG_PATH):
        return []
    with open(LOG_PATH, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    return [line.rstrip("\n") for line in lines[-n:]]
