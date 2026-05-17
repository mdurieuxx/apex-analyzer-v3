"""
Circular buffer recording raw Apex Timing WebSocket lines with timestamps.
Useful for offline analysis of message structure, column alternation patterns,
and pit lifecycle signals during a live race session.
"""
from collections import deque
from datetime import datetime, timezone

DEFAULT_MAXLEN = 2000  # roughly 10–20 min of traffic at typical update rates


class MessageRecorder:
    def __init__(self, maxlen: int = DEFAULT_MAXLEN):
        self._buf: deque[dict] = deque(maxlen=maxlen)

    def record(self, raw: str) -> None:
        self._buf.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "raw": raw,
        })

    def dump(self, limit: int = 500) -> list[dict]:
        msgs = list(self._buf)
        return msgs[-limit:] if limit < len(msgs) else msgs

    def clear(self) -> None:
        self._buf.clear()

    def __len__(self) -> int:
        return len(self._buf)


# Module-level singleton — imported by client.py and routes.py
recorder = MessageRecorder()
