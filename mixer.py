"""Passive, read-only estimation of a 3-point mixer valve position.

No command is ever written to the controller. The position is derived purely
by integrating how long the "auf"/"zu" relay outputs were observed active,
scaled by the configured actuator runtime. The estimate is only trusted
(calibrated) once a continuous single-direction run of >= runtime has been
observed, because that means the valve is known to be fully open or closed.
"""
from dataclasses import dataclass, field


@dataclass
class MixerAxis:
    zu_mod: int
    auf_mod: int
    position: float | None = None      # 0..100, None until a calibration event occurred
    direction: str = "halt"            # "auf" | "zu" | "halt"
    _last_ts: float | None = field(default=None, repr=False)
    _run_dir: str | None = field(default=None, repr=False)
    _run_since: float | None = field(default=None, repr=False)

    def update(self, zu_active: bool, auf_active: bool, runtime_s: float, now: float) -> None:
        dt = 0.0 if self._last_ts is None else max(0.0, now - self._last_ts)
        self._last_ts = now

        if auf_active and not zu_active:
            direction = "auf"
        elif zu_active and not auf_active:
            direction = "zu"
        else:
            direction = "halt"
        self.direction = direction

        if direction != self._run_dir:
            self._run_dir = direction
            self._run_since = now
        run_duration = 0.0 if self._run_since is None else now - self._run_since

        if direction != "halt" and self.position is not None and runtime_s > 0:
            delta = dt / runtime_s * 100.0
            self.position = min(100.0, max(0.0,
                self.position + (delta if direction == "auf" else -delta)))

        # Passive Kalibrierung: Steuerung faehrt selbst durchgehend bis zum Anschlag
        if direction != "halt" and runtime_s > 0 and run_duration >= runtime_s * 1.05:
            self.position = 100.0 if direction == "auf" else 0.0
