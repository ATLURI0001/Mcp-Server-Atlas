"""Mcp-Server-Atlas: tool call rate rotary telemetry."""
from collections import deque


class ToolCallRateRotary:
    def __init__(self, capacity: int = 10):
        self._buf: deque = deque(maxlen=capacity)

    def record(self, latency_ms: float) -> None:
        self._buf.append(latency_ms)

    def __len__(self) -> int:
        return len(self._buf)
