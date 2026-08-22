"""Configuration: load from config.json (priority) or fall back to env vars."""
import copy
import json
import logging
import os
from dataclasses import asdict, dataclass, field

log = logging.getLogger("hlc20.config")

_HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.getenv("CONFIG_PATH", os.path.join(_HERE, "data", "config.json"))

DEFAULT_SENSORS = [
    # Puffer
    {"id": "puff_oben",     "label": "Puff oben",      "mod": 3,   "kind": "temp", "error_raw": []},
    {"id": "puff_mitte",    "label": "Puff mitte",     "mod": 1,   "kind": "temp", "error_raw": []},
    {"id": "puff_unten",    "label": "Puff unten",     "mod": 12,  "kind": "temp", "error_raw": []},
    # Solar
    {"id": "sol_kollektor", "label": "Sol-Kollektor",  "mod": 69,  "kind": "temp", "error_raw": [4000]},
    {"id": "vorl_solar",    "label": "Vorl-Solar",     "mod": 80,  "kind": "temp", "error_raw": []},
    {"id": "rueckl_solar",  "label": "Rückl-Solar",    "mod": 81,  "kind": "temp", "error_raw": []},
    # Heizkreise
    {"id": "vl_ist_hk",     "label": "VL ist HK",      "mod": 45,  "kind": "temp", "error_raw": []},
    {"id": "vl_soll_hk",    "label": "VL soll HK",     "mod": 28,  "kind": "temp", "error_raw": []},
    {"id": "vl_ist_fbh",    "label": "VL ist FBH",     "mod": 152, "kind": "temp", "error_raw": []},
    {"id": "vl_soll_fbh",   "label": "VL soll FBH",    "mod": 143, "kind": "temp", "error_raw": []},
    # Weitere
    {"id": "aussenfuehler", "label": "Außenfühler",    "mod": 33,  "kind": "temp", "error_raw": []},
    {"id": "fuhl_zirku_bw", "label": "Fühl-Zirku-BW", "mod": 86,  "kind": "temp", "error_raw": []},
    {"id": "raum_temp",     "label": "Raum-Temp",      "mod": 173, "kind": "temp", "error_raw": [1800]},
    # Pumpen
    {"id": "pumpe_solar",   "label": "Pumpe Solar",    "mod": 75,  "kind": "pump", "error_raw": []},
    {"id": "pumpe_hk",      "label": "Pumpe HK",       "mod": 46,  "kind": "pump", "error_raw": []},
    {"id": "pumpe_fbh",     "label": "Pumpe FBH",      "mod": 153, "kind": "pump", "error_raw": []},
    {"id": "pumpe_zirk",    "label": "Pumpe Zirk",     "mod": 83,  "kind": "pump", "error_raw": []},
    {"id": "pumpe_kessel",  "label": "Pumpe Kessel",   "mod": 8,   "kind": "pump", "error_raw": []},
    # Betriebsstatus Schaltuhr (live aus Steuerung: 1 = Tagbetrieb aktiv)
    {"id": "hk_tagbetrieb",  "label": "HK Tagbetrieb",  "mod": 42,  "kind": "status", "error_raw": []},
    {"id": "fbh_tagbetrieb", "label": "FBH Tagbetrieb", "mod": 149, "kind": "status", "error_raw": []},
]

DEFAULT_PARAMS = [
    # HK Heizkurve (mod=28)
    {"id": "hk_nullpunkt",   "label": "HK Nullpunkt",          "mod": 28,  "idx": 0, "unit": "°C"},
    {"id": "hk_steigung",    "label": "HK Heizkurve Steigung",  "mod": 28,  "idx": 1, "unit": ""},
    {"id": "hk_max_soll",    "label": "HK Max Solltemp",        "mod": 28,  "idx": 2, "unit": "°C"},
    {"id": "hk_raumsoll",    "label": "HK Raumsoll",            "mod": 28,  "idx": 3, "unit": "°C"},
    {"id": "hk_nachtabs",    "label": "HK Nachtabsenkung",      "mod": 28,  "idx": 5, "unit": "K"},
    {"id": "hk_max_aussen",  "label": "HK Max Außentemp",       "mod": 28,  "idx": 9, "unit": "°C"},
    # FBH Heizkurve (mod=143)
    {"id": "fbh_nullpunkt",  "label": "FBH Nullpunkt",          "mod": 143, "idx": 0, "unit": "°C"},
    {"id": "fbh_steigung",   "label": "FBH Heizkurve Steigung", "mod": 143, "idx": 1, "unit": ""},
    {"id": "fbh_max_soll",   "label": "FBH Max Solltemp",       "mod": 143, "idx": 2, "unit": "°C"},
    {"id": "fbh_raumsoll",   "label": "FBH Raumsoll",           "mod": 143, "idx": 3, "unit": "°C"},
    {"id": "fbh_nachtabs",   "label": "FBH Nachtabsenkung",     "mod": 143, "idx": 5, "unit": "K"},
    {"id": "fbh_max_aussen", "label": "FBH Max Außentemp",      "mod": 143, "idx": 9, "unit": "°C"},
    # Betrieb
    {"id": "temp_nacht_ein", "label": "TempNacht ein",          "mod": 60,  "idx": 0, "unit": "°C"},
    {"id": "min_pu_hk_ein",  "label": "MinPu-HK-ein",           "mod": 66,  "idx": 0, "unit": "°C"},
    {"id": "zirk_min_ein",   "label": "Zirk-Min ein",           "mod": 88,  "idx": 0, "unit": "°C"},
    {"id": "zirk_max_aus",   "label": "Zirk-Max-aus",           "mod": 82,  "idx": 0, "unit": "°C"},
]


@dataclass
class Config:
    serial_host: str = ""
    serial_port: int = 10001
    mqtt_host: str = "mosquitto"
    mqtt_port: int = 1883
    mqtt_user: str = ""
    mqtt_password: str = ""
    poll_interval: int = 60
    device_topic: str = "hlc20"
    discovery_prefix: str = "homeassistant"
    sensors: list = field(default_factory=lambda: copy.deepcopy(DEFAULT_SENSORS))
    params: list = field(default_factory=lambda: copy.deepcopy(DEFAULT_PARAMS))


def _apply_env(cfg: Config) -> None:
    """Override still-default fields with env vars (first-run bootstrap)."""
    if not cfg.serial_host:
        cfg.serial_host = os.getenv("SILEX_HOST", "")
    if (p := os.getenv("SILEX_PORT")) and cfg.serial_port == 10001:
        cfg.serial_port = int(p)
    if h := os.getenv("MQTT_HOST"):
        cfg.mqtt_host = h
    if (p := os.getenv("MQTT_PORT")) and cfg.mqtt_port == 1883:
        cfg.mqtt_port = int(p)
    if u := os.getenv("MQTT_USER"):
        cfg.mqtt_user = u
    if pw := os.getenv("MQTT_PASSWORD"):
        cfg.mqtt_password = pw
    if (pi := os.getenv("POLL_INTERVAL")) and cfg.poll_interval == 60:
        cfg.poll_interval = int(pi)
    if dt := os.getenv("DEVICE_TOPIC"):
        cfg.device_topic = dt
    if dp := os.getenv("DISCOVERY_PREFIX"):
        cfg.discovery_prefix = dp


def load_config() -> Config:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                data = json.load(f)
            cfg = Config()
            for key in ("serial_host", "serial_port", "mqtt_host", "mqtt_port",
                        "mqtt_user", "mqtt_password", "poll_interval",
                        "device_topic", "discovery_prefix"):
                if key in data:
                    setattr(cfg, key, data[key])
            if "sensors" in data:
                cfg.sensors = data["sensors"]
            if "params" in data:
                cfg.params = data["params"]
            log.info("Config geladen: %s", CONFIG_PATH)
            return cfg
        except Exception as exc:
            log.warning("config.json fehlerhaft, nutze Env-Defaults: %s", exc)
    cfg = Config()
    _apply_env(cfg)
    return cfg


def save_config(cfg: Config) -> None:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(asdict(cfg), f, indent=2, ensure_ascii=False)
    log.info("Config gespeichert: %s", CONFIG_PATH)
