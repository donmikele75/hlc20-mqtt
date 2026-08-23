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
    {"id": "pumpe_hk",      "label": "Pumpe HK",       "mod": 43,  "kind": "pump", "error_raw": []},
    {"id": "pumpe_fbh",     "label": "Pumpe FBH",      "mod": 150, "kind": "pump", "error_raw": []},
    {"id": "pumpe_zirk",    "label": "Pumpe Zirk",     "mod": 83,  "kind": "pump", "error_raw": []},
    {"id": "pumpe_kessel",  "label": "Pumpe Kessel",   "mod": 8,   "kind": "pump", "error_raw": []},
    # Kessel
    {"id": "brenner",      "label": "Brenner",       "mod": 14,  "kind": "burner", "error_raw": []},
    # Betriebsstatus Schaltuhr (live aus Steuerung: 1 = Tagbetrieb aktiv)
    {"id": "hk_tagbetrieb",  "label": "HK Tagbetrieb",  "mod": 42,  "kind": "status", "error_raw": []},
    {"id": "fbh_tagbetrieb", "label": "FBH Tagbetrieb", "mod": 149, "kind": "status", "error_raw": []},
    # Mischer (Regler-Sollwert + Auf/Zu-Ausgänge, Module über .hlc-Analyse verifiziert)
    {"id": "mischer_hk_soll",  "label": "Mischer HK Soll",  "mod": 49,  "kind": "temp",  "error_raw": []},
    {"id": "mischer_hk_zu",    "label": "Mischer HK zu",    "mod": 50,  "kind": "mixer", "error_raw": []},
    {"id": "mischer_hk_auf",   "label": "Mischer HK auf",   "mod": 51,  "kind": "mixer", "error_raw": []},
    {"id": "mischer_fbh_soll", "label": "Mischer FBH Soll", "mod": 156, "kind": "temp",  "error_raw": []},
    {"id": "mischer_fbh_zu",   "label": "Mischer FBH zu",   "mod": 157, "kind": "mixer", "error_raw": []},
    {"id": "mischer_fbh_auf",  "label": "Mischer FBH auf",  "mod": 158, "kind": "mixer", "error_raw": []},
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
    # Puffer (Hysterese-Schwellen, kein kontinuierlicher Sollwert wie bei HK/FBH)
    {"id": "puffo_ein",     "label": "Puffer oben Einschalttemp",  "mod": 2,  "idx": 0, "unit": "°C"},
    {"id": "puffo_aus",     "label": "Puffer oben Ausschalttemp",  "mod": 2,  "idx": 1, "unit": "°C"},
    {"id": "puffm_ein",     "label": "Puffer mitte Einschalttemp", "mod": 21, "idx": 0, "unit": "°C"},
    {"id": "puffm_aus",     "label": "Puffer mitte Ausschalttemp", "mod": 21, "idx": 1, "unit": "°C"},
    # Wärmemengenzähler
    {"id": "waermemenge_kw",        "label": "Leistung",        "mod": 126, "idx": 1, "unit": "kW"},
    {"id": "waermemenge_kwh",       "label": "Energie gesamt",  "mod": 127, "idx": 1, "unit": "kWh"},
    {"id": "waermemenge_impuls_l",  "label": "Impuls/Liter",    "mod": 129, "idx": 1, "unit": "Imp/l"},
    {"id": "waermemenge_kwh_tag",   "label": "kWh Tag",         "mod": 131, "idx": 0, "unit": "kWh"},
    {"id": "waermemenge_kwh_vortag","label": "kWh Vortag",      "mod": 135, "idx": 1, "unit": "kWh"},
    {"id": "waermemenge_tageskwh",  "label": "TagKWH",          "mod": 142, "idx": 0, "unit": "kWh"},
    # Temperaturbegrenzung & Pumpenlogik
    {"id": "hk_tempbegrenzung",         "label": "HK Temperaturbegrenzung",   "mod": 55,  "idx": 0, "unit": "°C"},
    {"id": "fbh_tempbegrenzung",        "label": "FBH Temperaturbegrenzung",  "mod": 162, "idx": 0, "unit": "°C"},
    {"id": "min_pu_fbh_ein",            "label": "MinPu-FBH-ein",             "mod": 177, "idx": 0, "unit": "°C"},
    {"id": "kesselpumpe_ein_verzoegerung", "label": "Kesselpumpe Ein-Verzögerung", "mod": 9, "idx": 1, "unit": "min"},
    {"id": "kesselpumpe_aus_nachlauf",     "label": "Kesselpumpe Aus-Nachlauf",    "mod": 9, "idx": 4, "unit": "min"},
    {"id": "diff_pum_vl_hk_ein",   "label": "Diff-PuM-VL-HK EIN",   "mod": 15, "idx": 0, "unit": "K"},
    {"id": "diff_pum_vl_hk_aus",   "label": "Diff-PuM-VL-HK AUS",   "mod": 15, "idx": 1, "unit": "K"},
    {"id": "diff_kesselpumpe_vl_ein", "label": "DiffKess-Pu/VL EIN", "mod": 22, "idx": 4, "unit": "K"},
    {"id": "diff_kesselpumpe_vl_aus", "label": "DiffKess-Pu/VL AUS", "mod": 22, "idx": 5, "unit": "K"},
    # Solar-Vorrang (zwei Kreise, laut .hlc mit identischen Default-Werten konfiguriert)
    {"id": "solar1_min_temp",       "label": "Solar1 Min-Temp",         "mod": 68, "idx": 1, "unit": "°C"},
    {"id": "solar1_uebertemp_aus",  "label": "Solar1 Übertemp-Aus",     "mod": 68, "idx": 3, "unit": "°C"},
    {"id": "solar1_diff_ein",       "label": "Solar1 Temp-Diff-Ein",    "mod": 68, "idx": 4, "unit": "K"},
    {"id": "solar_max_temp_vorrang","label": "Solar Max-Temp Vorrang",  "mod": 74, "idx": 8,  "unit": "°C"},
    {"id": "solar_max_temp",        "label": "Solar Max-Temp",          "mod": 74, "idx": 13, "unit": "°C"},
    {"id": "solar2_min_temp_ein",   "label": "Solar2 Min-Temp-Ein",     "mod": 77, "idx": 1, "unit": "°C"},
    {"id": "solar2_uebertemp_aus",  "label": "Solar2 Übertemp-Aus",     "mod": 77, "idx": 3, "unit": "°C"},
    {"id": "solar2_diff_ein",       "label": "Solar2 Temp-Diff-Ein",    "mod": 77, "idx": 4, "unit": "K"},
    # Vorrang-Schalter & Nachtabsenkung
    {"id": "schalter_boilvorr_hk",  "label": "Schalter Boiler-Vorrang HK",  "mod": 62,  "idx": 0, "unit": ""},
    {"id": "schalter_boilvorr_fbh", "label": "Schalter Boiler-Vorrang FBH", "mod": 164, "idx": 0, "unit": ""},
    {"id": "fbh_tempnacht_ein",     "label": "FBH TempNacht ein",           "mod": 170, "idx": 0, "unit": "K"},
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
    mixer_poll_interval: float = 2.0   # Sekunden zwischen Mischer-Substatusabfragen (nur lesend)
    mixer_runtime_s: int = 110         # Angenommene volle Stellzeit des Mischerantriebs in Sekunden
    log_retention_days: int = 14       # Aufbewahrungsdauer der Anwendungs-Logdatei
    sensors: list = field(default_factory=lambda: copy.deepcopy(DEFAULT_SENSORS))
    params: list = field(default_factory=lambda: copy.deepcopy(DEFAULT_PARAMS))


def _apply_env(cfg: Config) -> None:
    """Override still-default fields with env vars (first-run bootstrap)."""
    if not cfg.serial_host:
        cfg.serial_host = os.getenv("SERIAL_HOST", "")
    if (p := os.getenv("SERIAL_PORT")) and cfg.serial_port == 10001:
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


def _merge_defaults(cfg: Config) -> list[str]:
    """Append default sensors/params whose id is missing (non-destructive migration)."""
    added: list[str] = []
    have_s = {s.get("id") for s in cfg.sensors}
    for d in DEFAULT_SENSORS:
        if d["id"] not in have_s:
            cfg.sensors.append(copy.deepcopy(d))
            added.append(d["id"])
    have_p = {p.get("id") for p in cfg.params}
    for d in DEFAULT_PARAMS:
        if d["id"] not in have_p:
            cfg.params.append(copy.deepcopy(d))
            added.append(d["id"])
    return added


def load_config() -> Config:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                data = json.load(f)
            cfg = Config()
            for key in ("serial_host", "serial_port", "mqtt_host", "mqtt_port",
                        "mqtt_user", "mqtt_password", "poll_interval",
                        "device_topic", "discovery_prefix",
                        "mixer_poll_interval", "mixer_runtime_s", "log_retention_days"):
                if key in data:
                    setattr(cfg, key, data[key])
            if "sensors" in data:
                cfg.sensors = data["sensors"]
            if "params" in data:
                cfg.params = data["params"]
            added = _merge_defaults(cfg)
            log.info("Config geladen: %s", CONFIG_PATH)
            if added:
                save_config(cfg)
                log.info("Fehlende Default-Einträge ergänzt: %s", ", ".join(added))
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
