"""Shared in-memory application state — safe to read from any thread."""
import asyncio
import threading


class AppState:
    def __init__(self) -> None:
        # Set from main.py after the event loop is running
        self.loop: asyncio.AbstractEventLoop | None = None
        self.broadcast_q: asyncio.Queue | None = None

        # One asyncio.Queue per connected WebSocket client
        self.ws_clients: dict[str, asyncio.Queue] = {}

        # Latest value per sensor/param id
        self.current_values: dict[str, dict] = {}

        # Connection state (written by poller thread, read by web routes)
        self.serial_connected: bool = False
        self.mqtt_connected: bool = False

        # Last completed poll metadata
        self.last_poll_ts: str = ""
        self.last_poll_errors: int = 0

        # Scan control flags (thread-safe Events)
        self.scan_requested = threading.Event()
        self.scan_stop = threading.Event()

    def emit(self, msg: dict) -> None:
        """Schedule delivery of *msg* to all WebSocket clients (thread-safe)."""
        if self.loop and self.broadcast_q and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self.broadcast_q.put_nowait, msg)
