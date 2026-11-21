"""Distributed Server Health Watchdog & Ping Heartbeat Rotary for MCP Servers."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class ServerHealthState(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"


@dataclass
class WatchdogConfig:
    ping_timeout_sec: float = 2.0
    consecutive_failures_threshold: int = 3
    degraded_latency_ms: float = 300.0
    recovery_cooldown_sec: float = 30.0
    latency_buffer_size: int = 100


@dataclass
class ServerHealthSnapshot:
    server_id: str
    state: ServerHealthState
    consecutive_failures: int
    total_pings: int
    successful_pings: int
    availability_pct: float
    last_ping_ms: Optional[float]
    p50_latency_ms: Optional[float]
    p90_latency_ms: Optional[float]
    p99_latency_ms: Optional[float]
    last_state_change_timestamp: float


class ServerHealthWatchdog:
    """Monitors live health, ping heartbeats, and latency distributions of registered MCP servers."""

    def __init__(self, config: Optional[WatchdogConfig] = None) -> None:
        self.config = config or WatchdogConfig()
        self._servers: Dict[str, _ServerRecord] = {}

    def register_server(self, server_id: str, transport: str = "stdio") -> None:
        """Registers a new server for health monitoring."""
        if not server_id or not isinstance(server_id, str):
            raise ValueError("server_id must be a non-empty string")
        if server_id in self._servers:
            raise ValueError(f"Server '{server_id}' is already registered")

        self._servers[server_id] = _ServerRecord(
            server_id=server_id,
            transport=transport,
            state=ServerHealthState.HEALTHY,
            last_state_change_timestamp=time.time(),
            max_latencies=self.config.latency_buffer_size,
        )

    def record_heartbeat(
        self,
        server_id: str,
        success: bool,
        latency_ms: Optional[float] = None,
        timestamp_sec: Optional[float] = None,
    ) -> ServerHealthState:
        """Records a ping heartbeat attempt and updates health state."""
        record = self._get_server(server_id)
        now = timestamp_sec if timestamp_sec is not None else time.time()

        record.total_pings += 1

        if success:
            record.successful_pings += 1
            record.consecutive_failures = 0
            lat = max(0.0, float(latency_ms if latency_ms is not None else 0.0))
            record.last_ping_ms = lat
            record.latencies.append(lat)
            if len(record.latencies) > record.max_latencies:
                record.latencies.pop(0)

            # Evaluate state
            p90 = record.calculate_percentile(90.0)
            if p90 is not None and p90 >= self.config.degraded_latency_ms:
                new_state = ServerHealthState.DEGRADED
            else:
                new_state = ServerHealthState.HEALTHY

            self._update_state(record, new_state, now)
        else:
            record.consecutive_failures += 1
            if record.consecutive_failures >= self.config.consecutive_failures_threshold:
                self._update_state(record, ServerHealthState.OFFLINE, now)

        return record.state

    def should_probe_offline_server(self, server_id: str, current_time: Optional[float] = None) -> bool:
        """Determines if an OFFLINE server has passed its recovery cooldown for a canary probe."""
        record = self._get_server(server_id)
        if record.state != ServerHealthState.OFFLINE:
            return False

        now = current_time if current_time is not None else time.time()
        elapsed = now - record.last_state_change_timestamp
        return elapsed >= self.config.recovery_cooldown_sec

    def get_snapshot(self, server_id: str) -> ServerHealthSnapshot:
        """Returns an immutable health snapshot of a monitored server."""
        record = self._get_server(server_id)
        avail = (
            (record.successful_pings / record.total_pings * 100.0)
            if record.total_pings > 0
            else 100.0
        )

        return ServerHealthSnapshot(
            server_id=record.server_id,
            state=record.state,
            consecutive_failures=record.consecutive_failures,
            total_pings=record.total_pings,
            successful_pings=record.successful_pings,
            availability_pct=round(avail, 2),
            last_ping_ms=record.last_ping_ms,
            p50_latency_ms=record.calculate_percentile(50.0),
            p90_latency_ms=record.calculate_percentile(90.0),
            p99_latency_ms=record.calculate_percentile(99.0),
            last_state_change_timestamp=record.last_state_change_timestamp,
        )

    def _get_server(self, server_id: str) -> _ServerRecord:
        if server_id not in self._servers:
            raise KeyError(f"Server '{server_id}' not found in watchdog registry")
        return self._servers[server_id]

    def _update_state(self, record: _ServerRecord, new_state: ServerHealthState, timestamp: float) -> None:
        if record.state != new_state:
            record.state = new_state
            record.last_state_change_timestamp = timestamp


class _ServerRecord:
    def __init__(
        self,
        server_id: str,
        transport: str,
        state: ServerHealthState,
        last_state_change_timestamp: float,
        max_latencies: int = 100,
    ) -> None:
        self.server_id = server_id
        self.transport = transport
        self.state = state
        self.last_state_change_timestamp = last_state_change_timestamp
        self.consecutive_failures = 0
        self.total_pings = 0
        self.successful_pings = 0
        self.last_ping_ms: Optional[float] = None
        self.latencies: List[float] = []
        self.max_latencies = max_latencies

    def calculate_percentile(self, p: float) -> Optional[float]:
        if not self.latencies:
            return None
        sorted_lats = sorted(self.latencies)
        k = (len(sorted_lats) - 1) * (p / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return round(sorted_lats[int(k)], 2)
        d0 = sorted_lats[int(f)] * (c - k)
        d1 = sorted_lats[int(c)] * (k - f)
        return round(d0 + d1, 2)
