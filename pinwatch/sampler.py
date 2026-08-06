"""Background polling thread so the UI never blocks on a driver call."""

from __future__ import annotations

import threading
import time
from collections import deque

from .nvml import PowerSource, Sample


class Sampler:
    def __init__(self, source: PowerSource, interval_s: float = 0.25, history: int = 480):
        self.source = source
        self.interval_s = interval_s
        self._lock = threading.Lock()
        self._history: deque[tuple[float, float]] = deque(maxlen=history)
        self._latest: Sample | None = None
        self._error: str | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="pinwatch-sampler", daemon=True)
        self.started_at = time.monotonic()
        self.peak_w = 0.0
        self.samples = 0

    def start(self) -> "Sampler":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
        self.source.close()

    def _run(self) -> None:
        while not self._stop.is_set():
            began = time.monotonic()
            try:
                sample = self.source.read()
            except Exception as exc:  # a transient driver hiccup must not kill the UI
                with self._lock:
                    self._error = str(exc)
            else:
                with self._lock:
                    self._latest = sample
                    self._error = None
                    self._history.append((began, sample.watts))
                    self.peak_w = max(self.peak_w, sample.watts)
                    self.samples += 1
            # Drift-free pacing: sleep the remainder, not the full interval.
            self._stop.wait(max(0.0, self.interval_s - (time.monotonic() - began)))

    def latest(self) -> tuple[Sample | None, str | None]:
        with self._lock:
            return self._latest, self._error

    def history(self) -> list[tuple[float, float]]:
        with self._lock:
            return list(self._history)

    def reset_peak(self) -> None:
        with self._lock:
            self.peak_w = self._latest.watts if self._latest else 0.0

    @property
    def capacity(self) -> int:
        return self._history.maxlen or 0

    @property
    def uptime_s(self) -> float:
        return time.monotonic() - self.started_at
