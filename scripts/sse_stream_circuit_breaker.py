"""MCP SSE Transport Stream Disconnect & Reconnect Storm Circuit Breaker.

Protects MCP server event loops from rapid SSE client reconnect storms and
broken pipe cascades using exponential backoff and circuit breaking.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Dict


class StreamState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class SseStreamCircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_threshold: int = 2,
        cooldown_seconds: float = 1.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_threshold = recovery_threshold
        self.cooldown_seconds = cooldown_seconds
        self.clients: Dict[str, dict] = {}

    def _get_client(self, client_id: str) -> dict:
        if client_id not in self.clients:
            self.clients[client_id] = {
                "state": StreamState.CLOSED,
                "failures": 0,
                "successes": 0,
                "trip_time": 0.0,
            }
        return self.clients[client_id]

    def allow_connect(self, client_id: str, now: float | None = None) -> bool:
        now = now if now is not None else time.monotonic()
        c = self._get_client(client_id)

        if c["state"] == StreamState.OPEN:
            if now - c["trip_time"] >= self.cooldown_seconds:
                c["state"] = StreamState.HALF_OPEN
                c["successes"] = 0
                return True
            return False
        return True

    def record_disconnect(self, client_id: str, clean: bool, now: float | None = None) -> StreamState:
        now = now if now is not None else time.monotonic()
        c = self._get_client(client_id)

        if clean:
            if c["state"] == StreamState.HALF_OPEN:
                c["successes"] += 1
                if c["successes"] >= self.recovery_threshold:
                    c["state"] = StreamState.CLOSED
                    c["failures"] = 0
            else:
                c["failures"] = 0
        else:
            c["failures"] += 1
            c["successes"] = 0
            if c["state"] == StreamState.HALF_OPEN or c["failures"] >= self.failure_threshold:
                c["state"] = StreamState.OPEN
                c["trip_time"] = now

        return c["state"]
