"""
MCP Server Subprocess Watchdog & Zombie Deadlock Sentinel.

Guards against unresponsive MCP server subprocesses, enforces execution timeouts,
reaps stalled background workers, and applies circuit-breaking quarantine to flaky servers.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ProcessHealthState(str, Enum):
    STARTING = "STARTING"
    HEALTHY = "HEALTHY"
    UNRESPONSIVE = "UNRESPONSIVE"
    QUARANTINED = "QUARANTINED"
    TERMINATED = "TERMINATED"


class WatchdogError(Exception):
    """Raised when an operation is attempted on an invalid or quarantined server process."""
    pass


@dataclass
class ProcessDescriptor:
    server_id: str
    pid: int
    state: ProcessHealthState = ProcessHealthState.STARTING
    started_at: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)
    consecutive_failures: int = 0
    quarantined_at: Optional[float] = None


@dataclass
class WatchdogConfig:
    heartbeat_timeout_sec: float = 10.0
    max_consecutive_failures: int = 3
    quarantine_cooldown_sec: float = 60.0


class SubprocessWatchdog:
    """Monitors subprocess health, reaps deadlocks, and enforces server isolation."""

    def __init__(self, config: Optional[WatchdogConfig] = None) -> None:
        self.config = config or WatchdogConfig()
        self.processes: Dict[str, ProcessDescriptor] = {}

        self._timeouts_detected = 0
        self._quarantines_enforced = 0
        self._reaped_count = 0

    def register_process(
        self,
        server_id: str,
        pid: int,
        start_time: Optional[float] = None,
    ) -> ProcessDescriptor:
        """Registers a newly spawned MCP server process for watchdog tracking."""
        if not server_id or not isinstance(server_id, str):
            raise ValueError("server_id must be a non-empty string")
        if not isinstance(pid, int) or pid <= 0:
            raise ValueError("pid must be a positive integer")

        clean_id = server_id.strip()
        now = start_time if start_time is not None else time.time()

        # Check existing quarantine status
        if clean_id in self.processes:
            existing = self.processes[clean_id]
            if existing.state == ProcessHealthState.QUARANTINED:
                if existing.quarantined_at and (now - existing.quarantined_at) < self.config.quarantine_cooldown_sec:
                    raise WatchdogError(
                        f"Server '{clean_id}' is currently quarantined until cooldown expires"
                    )

        desc = ProcessDescriptor(
            server_id=clean_id,
            pid=pid,
            state=ProcessHealthState.STARTING,
            started_at=now,
            last_heartbeat=now,
            consecutive_failures=0,
            quarantined_at=None,
        )
        self.processes[clean_id] = desc
        return desc

    def record_heartbeat(
        self,
        server_id: str,
        timestamp: Optional[float] = None,
    ) -> bool:
        """Records a successful response/heartbeat from the server, confirming healthy state."""
        clean_id = server_id.strip() if server_id else ""
        if clean_id not in self.processes:
            return False

        proc = self.processes[clean_id]
        if proc.state in (ProcessHealthState.TERMINATED, ProcessHealthState.QUARANTINED):
            return False

        now = timestamp if timestamp is not None else time.time()
        proc.last_heartbeat = now
        proc.state = ProcessHealthState.HEALTHY
        proc.consecutive_failures = 0
        return True

    def record_failure(
        self,
        server_id: str,
        timestamp: Optional[float] = None,
    ) -> ProcessHealthState:
        """Records an execution error, timeout, or abrupt exit for the server."""
        clean_id = server_id.strip() if server_id else ""
        if clean_id not in self.processes:
            raise ValueError(f"Unknown server_id: {clean_id}")

        proc = self.processes[clean_id]
        now = timestamp if timestamp is not None else time.time()

        proc.consecutive_failures += 1
        if proc.consecutive_failures >= self.config.max_consecutive_failures:
            proc.state = ProcessHealthState.QUARANTINED
            proc.quarantined_at = now
            self._quarantines_enforced += 1
        else:
            proc.state = ProcessHealthState.UNRESPONSIVE

        return proc.state

    def scan_and_reap(
        self,
        current_time: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Scans tracked processes, flagging unresponsive deadlocks and transitioning states."""
        now = current_time if current_time is not None else time.time()
        reaped: List[Dict[str, Any]] = []

        for server_id, proc in list(self.processes.items()):
            if proc.state in (ProcessHealthState.TERMINATED, ProcessHealthState.QUARANTINED):
                # Check if quarantine cooldown elapsed
                if proc.state == ProcessHealthState.QUARANTINED and proc.quarantined_at:
                    if (now - proc.quarantined_at) >= self.config.quarantine_cooldown_sec:
                        proc.state = ProcessHealthState.TERMINATED
                continue

            elapsed_since_heartbeat = now - proc.last_heartbeat
            if elapsed_since_heartbeat > self.config.heartbeat_timeout_sec:
                self._timeouts_detected += 1
                self._reaped_count += 1
                prev_state = proc.state
                new_state = self.record_failure(server_id, timestamp=now)

                reaped.append({
                    "server_id": server_id,
                    "pid": proc.pid,
                    "previous_state": prev_state,
                    "new_state": new_state,
                    "elapsed_sec": round(elapsed_since_heartbeat, 2),
                })

        return reaped

    def can_spawn(
        self,
        server_id: str,
        current_time: Optional[float] = None,
    ) -> bool:
        """Returns True if the server is permitted to spawn (not quarantined)."""
        clean_id = server_id.strip() if server_id else ""
        if clean_id not in self.processes:
            return True

        proc = self.processes[clean_id]
        if proc.state == ProcessHealthState.QUARANTINED:
            now = current_time if current_time is not None else time.time()
            if proc.quarantined_at and (now - proc.quarantined_at) < self.config.quarantine_cooldown_sec:
                return False
            # Cooldown passed
            proc.state = ProcessHealthState.TERMINATED
            return True

        return True

    def terminate_process(self, server_id: str) -> bool:
        """Marks a process as cleanly terminated and removes active locks."""
        clean_id = server_id.strip() if server_id else ""
        if clean_id in self.processes:
            self.processes[clean_id].state = ProcessHealthState.TERMINATED
            return True
        return False

    def get_telemetry(self) -> Dict[str, Any]:
        """Returns live operational observability metrics."""
        healthy_count = sum(1 for p in self.processes.values() if p.state == ProcessHealthState.HEALTHY)
        quarantined_count = sum(1 for p in self.processes.values() if p.state == ProcessHealthState.QUARANTINED)
        unresponsive_count = sum(1 for p in self.processes.values() if p.state == ProcessHealthState.UNRESPONSIVE)

        return {
            "total_tracked": len(self.processes),
            "active_healthy": healthy_count,
            "active_quarantined": quarantined_count,
            "active_unresponsive": unresponsive_count,
            "timeouts_detected": self._timeouts_detected,
            "quarantines_enforced": self._quarantines_enforced,
            "reaped_count": self._reaped_count,
        }
