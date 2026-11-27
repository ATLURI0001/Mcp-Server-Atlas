"""atlas_session_rotary.py – bounded ring buffer for atlas session IDs."""
from collections import deque


class AtlasSessionRotary:
    def __init__(self, max_size: int = 10):
        self._buf: deque = deque(maxlen=max_size)

    def push(self, sid: str) -> None:
        self._buf.append(sid)

    def count(self) -> int:
        return len(self._buf)
