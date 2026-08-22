#!/usr/bin/env python3
"""Entry point: load config, wire up AppState, start PollerThread + uvicorn."""
import asyncio
import logging
import os

import uvicorn

from config import load_config
from poller import PollerThread
from state import AppState
import web as web_module

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("hlc20")


async def _main() -> None:
    cfg = load_config()
    if not cfg.serial_host:
        log.warning("SILEX_HOST nicht gesetzt – Serial inaktiv bis Einstellungen gespeichert")

    state = AppState()
    state.broadcast_q = asyncio.Queue(maxsize=2000)
    state.loop = asyncio.get_running_loop()

    cfg_ref = [cfg]

    # Wire globals into FastAPI app.state
    web_module.app.state.hlc     = state
    web_module.app.state.cfg_ref = cfg_ref

    poller = PollerThread(state, cfg_ref)
    web_module.app.state.poller = poller
    poller.start()
    log.info("Poller gestartet")

    port = int(os.getenv("WEB_PORT", "80"))
    config = uvicorn.Config(
        web_module.app,
        host="0.0.0.0",
        port=port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)
    log.info("Web-UI startet auf Port %d", port)
    await server.serve()

    poller.stop()
    poller.join(timeout=5)
    log.info("Beendet")


if __name__ == "__main__":
    asyncio.run(_main())
