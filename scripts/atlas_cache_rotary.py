"""atlas_cache_rotary.py – bounded ring buffer for atlas cache events."""
from collections import deque


class AtlasCacheRotary:
    def __init__(self, max_size: int = 10):
        self._buf: deque = deque(maxlen=max_size)

    def push(self, key: str) -> None:
        self._buf.append(key)

    def latest(self) -> list:
        return list(self._buf)

    def count(self) -> int:
        return len(self._buf)
