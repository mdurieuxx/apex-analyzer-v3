"""
Rolling track condition monitor.

As the race progresses, the track rubbers in and lap times improve.
We track the reference time as the rolling average of the top fraction of
recent laps so that all lap comparisons are relative to current conditions,
not absolute times.
"""
from collections import deque
import statistics


class TrackConditionMonitor:
    def __init__(self, window: int = 40, top_frac: float = 0.25):
        self._window: deque[int] = deque(maxlen=window)
        self._top_frac = top_frac
        self._MIN_LAP_MS = 30_000
        self._MAX_LAP_MS = 300_000

    def add_lap(self, ms: int) -> None:
        if self._MIN_LAP_MS < ms < self._MAX_LAP_MS:
            self._window.append(ms)

    def reference_ms(self) -> float | None:
        """Current reference time = mean of top-N fastest recent laps."""
        if len(self._window) < 5:
            return None
        sorted_laps = sorted(self._window)
        n = max(1, int(len(sorted_laps) * self._top_frac))
        return statistics.mean(sorted_laps[:n])

    def normalize(self, ms: int) -> float | None:
        """
        Return lap time as a ratio to the current reference.
        1.00 = matching the current fastest pace.
        1.05 = 5% slower than the current fastest pace.
        Returns None if not enough data yet.
        """
        ref = self.reference_ms()
        if ref is None or ref == 0:
            return None
        if not (self._MIN_LAP_MS < ms < self._MAX_LAP_MS):
            return None
        return ms / ref

    def has_reference(self) -> bool:
        return len(self._window) >= 5
