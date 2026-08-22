"""FastAPI web application: routes, WebSocket, HTMX partials."""
import asyncio
import json
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import Config, save_config
from hlc_parser import parse_hlc
import paho.mqtt.client as mqtt
from protocol import hlc_open
from state import AppState

log = logging.getLogger("hlc20.web")

_HERE = os.path.dirname(os.path.abspath(__file__))
_TEMPLATES = os.path.join(_HERE, "templates")
templates = Jinja2Templates(directory=_TEMPLATES)
_executor = ThreadPoolExecutor(max_workers=2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_broadcast_fanout(app.state.hlc))
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="HLC-20 Web-UI", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=os.path.join(_HERE, "static")), name="static")


async def _broadcast_fanout(state: AppState) -> None:
    """Fan out every message from broadcast_q to all connected WS clients."""
    q = state.broadcast_q
    while True:
        try:
            msg = await q.get()
            dead = []
            for cid, cq in list(state.ws_clients.items()):
                try:
                    cq.put_nowait(msg)
                except asyncio.QueueFull:
                    dead.append(cid)
            for cid in dead:
                state.ws_clients.pop(cid, None)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            log.error("Broadcast-Fehler: %s", exc)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _s(request: Request) -> AppState:
    return request.app.state.hlc

def _c(request: Request) -> Config:
    return request.app.state.cfg_ref[0]

def _p(request: Request):
    return request.app.state.poller

def _ctx(page: str, **kw) -> dict:
    return {"active_page": page, **kw}


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    cfg = _c(request)
    return templates.TemplateResponse(request, "index.html", _ctx(
        "dashboard",
        values=_s(request).current_values,
        sensors=cfg.sensors,
        params=cfg.params,
    ))


@app.get("/bus-monitor", response_class=HTMLResponse)
async def bus_monitor_page(request: Request):
    return templates.TemplateResponse(request, "bus_monitor.html", _ctx("bus_monitor"))


@app.get("/anlagenschema", response_class=HTMLResponse)
async def anlagenschema_page(request: Request):
    return templates.TemplateResponse(request, "anlagenschema.html", _ctx(
        "anlagenschema",
        values=_s(request).current_values,
    ))


@app.get("/sensoren", response_class=HTMLResponse)
async def sensoren_page(request: Request):
    cfg = _c(request)
    return templates.TemplateResponse(request, "sensoren.html", _ctx(
        "sensoren",
        sensors=cfg.sensors,
        params=cfg.params,
        cfg=cfg,
        mixer_values={
            k: v for k, v in _s(request).current_values.items()
            if k in ("mischer_hk_position", "mischer_fbh_position")
        },
    ))


@app.get("/einstellungen", response_class=HTMLResponse)
async def einstellungen_page(request: Request):
    return templates.TemplateResponse(request, "einstellungen.html", _ctx(
        "einstellungen",
        cfg=_c(request),
    ))


@app.get("/hlc-analyse", response_class=HTMLResponse)
async def hlc_analyse_page(request: Request):
    return templates.TemplateResponse(request, "hlc_upload.html", _ctx("hlc_analyse"))


@app.post("/api/hlc-parse")
async def hlc_parse_route(request: Request, file: UploadFile = File(...)):
    if file.size and file.size > 10 * 1024 * 1024:
        raise HTTPException(413, "Datei zu groß (max 10 MB)")
    data = await file.read()
    if len(data) < 20:
        raise HTTPException(400, "Datei zu klein oder leer")

    module_map = parse_hlc(data)
    if not module_map:
        raise HTTPException(422, "Keine Module gefunden – ist es eine gültige .hlc-Datei?")

    cfg = _c(request)
    known_sensors = {s["mod"]: {"id": s["id"], "label": s["label"], "kind": "sensor"}
                     for s in cfg.sensors}
    known_params  = {p["mod"]: {"id": p["id"], "label": p["label"], "kind": "param"}
                     for p in cfg.params}

    modules = []
    for mod in sorted(module_map):
        labels = module_map[mod]
        in_cfg = known_sensors.get(mod) or known_params.get(mod)
        modules.append({
            "mod":      mod,
            "hex":      f"0x{mod:02X}",
            "labels":   labels,
            "label":    labels[0] if labels else "",
            "in_config": in_cfg,
        })

    return JSONResponse({
        "filename":    file.filename,
        "file_size":   len(data),
        "total":       len(module_map),
        "in_config":   sum(1 for m in modules if m["in_config"]),
        "modules":     modules,
    })


# ── API: Status & Values ──────────────────────────────────────────────────────

@app.get("/api/status-html", response_class=HTMLResponse)
async def status_html(request: Request):
    state = _s(request)
    return templates.TemplateResponse(request, "_status.html", {
        "serial_connected": state.serial_connected,
        "mqtt_connected":   state.mqtt_connected,
        "last_poll_ts":     state.last_poll_ts,
    })


@app.get("/api/values")
async def api_values(request: Request):
    return JSONResponse(_s(request).current_values)


@app.get("/api/dashboard-partial", response_class=HTMLResponse)
async def dashboard_partial(request: Request):
    cfg = _c(request)
    return templates.TemplateResponse(request, "_dashboard_values.html", {
        "values":   _s(request).current_values,
        "sensors":  cfg.sensors,
        "params":   cfg.params,
    })


# ── API: Scan ─────────────────────────────────────────────────────────────────

@app.post("/api/scan/start")
async def scan_start(request: Request):
    state = _s(request)
    if state.scan_requested.is_set():
        return JSONResponse({"status": "already_running"})
    state.scan_stop.clear()
    state.scan_requested.set()
    return JSONResponse({"status": "started"})


@app.post("/api/scan/stop")
async def scan_stop(request: Request):
    _s(request).scan_stop.set()
    return JSONResponse({"status": "stopping"})


# ── WebSocket: Bus monitor ────────────────────────────────────────────────────

@app.websocket("/ws/bus-monitor")
async def ws_bus_monitor(ws: WebSocket):
    state: AppState = ws.app.state.hlc
    await ws.accept()
    cid = str(uuid.uuid4())
    cq: asyncio.Queue = asyncio.Queue(maxsize=500)
    state.ws_clients[cid] = cq
    log.debug("WS verbunden: %s", cid[:8])
    try:
        while True:
            msg = await cq.get()
            await ws.send_json(msg)
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        state.ws_clients.pop(cid, None)
        log.debug("WS getrennt: %s", cid[:8])


# ── API: Sensor CRUD ──────────────────────────────────────────────────────────

@app.post("/api/sensors/add")
async def sensor_add(
    request: Request,
    sid: str = Form(),
    label: str = Form(),
    mod: int = Form(),
    kind: str = Form(default="temp"),
    error_raw: str = Form(default=""),
):
    cfg = _c(request)
    if any(s["id"] == sid for s in cfg.sensors):
        raise HTTPException(400, "Sensor-ID bereits vorhanden")
    errs = [int(x.strip()) for x in error_raw.split(",")
            if x.strip().lstrip("-").isdigit()]
    cfg.sensors.append({"id": sid, "label": label, "mod": mod,
                        "kind": kind, "error_raw": errs})
    save_config(cfg)
    _p(request).request_reload()
    return JSONResponse({"status": "ok", "id": sid})


@app.post("/api/sensors/{sid}/update")
async def sensor_update(
    request: Request,
    sid: str,
    label: str = Form(),
    mod: int = Form(),
    kind: str = Form(default="temp"),
    error_raw: str = Form(default=""),
):
    cfg = _c(request)
    i = next((i for i, s in enumerate(cfg.sensors) if s["id"] == sid), None)
    if i is None:
        raise HTTPException(404, "Sensor nicht gefunden")
    errs = [int(x.strip()) for x in error_raw.split(",")
            if x.strip().lstrip("-").isdigit()]
    cfg.sensors[i] = {"id": sid, "label": label, "mod": mod,
                      "kind": kind, "error_raw": errs}
    save_config(cfg)
    _p(request).request_reload()
    return JSONResponse({"status": "ok"})


@app.delete("/api/sensors/{sid}")
async def sensor_delete(request: Request, sid: str):
    cfg = _c(request)
    cfg.sensors = [s for s in cfg.sensors if s["id"] != sid]
    save_config(cfg)
    return JSONResponse({"status": "ok"})


# ── API: Param CRUD ───────────────────────────────────────────────────────────

@app.post("/api/params/add")
async def param_add(
    request: Request,
    pid: str = Form(),
    label: str = Form(),
    mod: int = Form(),
    idx: int = Form(),
    unit: str = Form(default="°C"),
):
    cfg = _c(request)
    if any(p["id"] == pid for p in cfg.params):
        raise HTTPException(400, "Parameter-ID bereits vorhanden")
    cfg.params.append({"id": pid, "label": label, "mod": mod,
                       "idx": idx, "unit": unit})
    save_config(cfg)
    _p(request).request_reload()
    return JSONResponse({"status": "ok", "id": pid})


@app.post("/api/params/{pid}/update")
async def param_update(
    request: Request,
    pid: str,
    label: str = Form(),
    mod: int = Form(),
    idx: int = Form(),
    unit: str = Form(default="°C"),
):
    cfg = _c(request)
    i = next((i for i, p in enumerate(cfg.params) if p["id"] == pid), None)
    if i is None:
        raise HTTPException(404, "Parameter nicht gefunden")
    cfg.params[i] = {"id": pid, "label": label, "mod": mod,
                     "idx": idx, "unit": unit}
    save_config(cfg)
    _p(request).request_reload()
    return JSONResponse({"status": "ok"})


@app.delete("/api/params/{pid}")
async def param_delete(request: Request, pid: str):
    cfg = _c(request)
    cfg.params = [p for p in cfg.params if p["id"] != pid]
    save_config(cfg)
    return JSONResponse({"status": "ok"})


# ── API: Settings ─────────────────────────────────────────────────────────────

@app.post("/api/einstellungen", response_class=HTMLResponse)
async def save_einstellungen(
    request: Request,
    serial_host: str = Form(),
    serial_port: int = Form(),
    mqtt_host: str = Form(default=""),
    mqtt_port: int = Form(default=1883),
    mqtt_user: str = Form(default=""),
    mqtt_password: str = Form(default=""),
    poll_interval: int = Form(default=60),
    device_topic: str = Form(default="hlc20"),
    discovery_prefix: str = Form(default="homeassistant"),
):
    cfg = _c(request)
    reconnect = (
        cfg.serial_host != serial_host or cfg.serial_port != serial_port or
        cfg.mqtt_host   != mqtt_host   or cfg.mqtt_port   != mqtt_port   or
        cfg.mqtt_user   != mqtt_user   or cfg.mqtt_password != mqtt_password
    )
    cfg.serial_host     = serial_host
    cfg.serial_port     = serial_port
    cfg.mqtt_host       = mqtt_host
    cfg.mqtt_port       = mqtt_port
    cfg.mqtt_user       = mqtt_user
    cfg.mqtt_password   = mqtt_password
    cfg.poll_interval   = poll_interval
    cfg.device_topic    = device_topic
    cfg.discovery_prefix = discovery_prefix
    save_config(cfg)
    if reconnect:
        _p(request).request_reload()
    suffix = " – Verbindung wird neu aufgebaut…" if reconnect else ""
    return HTMLResponse(
        f'<span class="text-green-400 font-medium">✓ Gespeichert{suffix}</span>'
    )


@app.post("/api/mischer-einstellungen", response_class=HTMLResponse)
async def save_mischer_einstellungen(
    request: Request,
    mixer_poll_interval: float = Form(default=2.0),
    mixer_runtime_s: int = Form(default=110),
):
    cfg = _c(request)
    cfg.mixer_poll_interval = max(0.5, mixer_poll_interval)
    cfg.mixer_runtime_s = max(1, mixer_runtime_s)
    save_config(cfg)
    return HTMLResponse(
        '<span class="text-green-400 font-medium">✓ Gespeichert</span>'
    )


@app.post("/api/test-serial", response_class=HTMLResponse)
async def test_serial(
    serial_host: str = Form(),
    serial_port: int = Form(),
):
    loop = asyncio.get_running_loop()
    def _do() -> str:
        ser, echo = hlc_open(serial_host, serial_port)
        ser.close()
        return echo or "kein Handshake-Echo"
    try:
        echo = await loop.run_in_executor(_executor, _do)
        return HTMLResponse(
            f'<span class="text-green-400 font-medium">✓ Verbunden – Echo: {echo}</span>'
        )
    except Exception as exc:
        return HTMLResponse(
            f'<span class="text-red-400 font-medium">✗ Fehler: {exc}</span>'
        )


@app.post("/api/test-mqtt", response_class=HTMLResponse)
async def test_mqtt(
    mqtt_host: str = Form(default=""),
    mqtt_port: int = Form(default=1883),
    mqtt_user: str = Form(default=""),
    mqtt_password: str = Form(default=""),
    device_topic: str = Form(default="hlc20"),
):
    if not mqtt_host:
        return HTMLResponse('<span class="text-yellow-400 font-medium">⚠ Kein MQTT-Host angegeben</span>')
    loop = asyncio.get_running_loop()
    def _do() -> str:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="hlc20_test")
        if mqtt_user:
            client.username_pw_set(mqtt_user, mqtt_password)
        client.connect(mqtt_host, mqtt_port, keepalive=10)
        client.loop_start()
        test_topic = f"{device_topic}/test"
        payload = json.dumps({"source": "hlc20-bridge", "test": True, "value": 99.9})
        info = client.publish(test_topic, payload)
        info.wait_for_publish(timeout=5)
        client.loop_stop()
        client.disconnect()
        return test_topic
    try:
        topic = await loop.run_in_executor(_executor, _do)
        return HTMLResponse(
            f'<span class="text-green-400 font-medium">✓ Verbunden – Testnachricht an <code>{topic}</code> gesendet</span>'
        )
    except Exception as exc:
        return HTMLResponse(
            f'<span class="text-red-400 font-medium">✗ Fehler: {exc}</span>'
        )
