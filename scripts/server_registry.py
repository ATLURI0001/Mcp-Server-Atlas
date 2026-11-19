#!/usr/bin/env python3
"""
MCP Server Capability Registry & Health Probe Engine (Mcp-Server-Atlas)

Provides:
- Manifest parsing for MCP server capabilities (tools, resources, prompts).
- Semver specification parsing and compatibility matching.
- Health probe manager with stateful circuit breaker (HEALTHY, DEGRADED, FAILING).
- Jittered latency tracking and percentiles calculation (p50, p95, p99).
"""

from __future__ import annotations

import dataclasses
import enum
import math
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple


class HealthStatus(enum.Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    FAILING = "FAILING"
    UNKNOWN = "UNKNOWN"


@dataclasses.dataclass(frozen=True)
class McpToolDefinition:
    """Metadata for an individual MCP tool exposed by a server."""
    name: str
    description: str
    required_params: Set[str] = dataclasses.field(default_factory=set)
    optional_params: Set[str] = dataclasses.field(default_factory=set)


@dataclasses.dataclass(frozen=True)
class McpServerManifest:
    """Registry definition for an MCP server package."""
    server_id: str
    display_name: str
    version: str
    homepage: str
    tools: Tuple[McpToolDefinition, ...] = dataclasses.field(default_factory=tuple)
    supported_transports: Set[str] = dataclasses.field(default_factory=lambda: {"stdio", "sse"})


def parse_semver(version_str: str) -> Tuple[int, int, int]:
    """Parse a semantic version 'X.Y.Z' into integer tuple."""
    clean = version_str.strip().lstrip("v")
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", clean)
    if not match:
        raise ValueError(f"Invalid semver string: {version_str}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def satisfies_semver(version_str: str, constraint: str) -> bool:
    """
    Check if version_str satisfies a basic semver constraint:
    Supports '^X.Y.Z', '>=X.Y.Z', '==X.Y.Z', and '*'.
    """
    constraint = constraint.strip()
    if constraint in ("*", "", "any"):
        return True

    major, minor, patch = parse_semver(version_str)

    if constraint.startswith("^"):
        req_major, req_minor, req_patch = parse_semver(constraint[1:])
        if major != req_major:
            return False
        return (minor, patch) >= (req_minor, req_patch)

    if constraint.startswith(">="):
        req = parse_semver(constraint[2:])
        return (major, minor, patch) >= req

    if constraint.startswith("=="):
        req = parse_semver(constraint[2:])
        return (major, minor, patch) == req

    # Plain version string treated as exact match
    req = parse_semver(constraint)
    return (major, minor, patch) == req


@dataclasses.dataclass
class ServerHealthRecord:
    server_id: str
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    total_probes: int = 0
    latencies_ms: List[float] = dataclasses.field(default_factory=list)
    status: HealthStatus = HealthStatus.UNKNOWN
    last_probe_time: Optional[float] = None


class ServerRegistryEngine:
    """Registry index and health monitoring coordinator for MCP servers."""

    def __init__(
        self,
        failure_threshold: int = 3,
        degrade_threshold: int = 1,
        latency_window_size: int = 100,
    ) -> None:
        if failure_threshold <= 0 or degrade_threshold < 0:
            raise ValueError("Thresholds must be positive integers")
        self.failure_threshold = failure_threshold
        self.degrade_threshold = degrade_threshold
        self.latency_window_size = latency_window_size
        self._servers: Dict[str, McpServerManifest] = {}
        self._health: Dict[str, ServerHealthRecord] = {}

    def register(self, manifest: McpServerManifest) -> None:
        """Register or update an MCP server in the registry catalog."""
        parse_semver(manifest.version)  # Validate semver
        self._servers[manifest.server_id] = manifest
        if manifest.server_id not in self._health:
            self._health[manifest.server_id] = ServerHealthRecord(server_id=manifest.server_id)

    def unregister(self, server_id: str) -> bool:
        """Remove a server from registry."""
        if server_id in self._servers:
            del self._servers[server_id]
            self._health.pop(server_id, None)
            return True
        return False

    def find_servers_for_tool(
        self,
        tool_name: str,
        required_params: Optional[Set[str]] = None,
        version_constraint: Optional[str] = None,
    ) -> List[McpServerManifest]:
        """Query servers providing tool_name matching parameter schema and version constraint."""
        matching: List[McpServerManifest] = []
        for s in self._servers.values():
            if version_constraint and not satisfies_semver(s.version, version_constraint):
                continue
            for t in s.tools:
                if t.name == tool_name:
                    if required_params and not required_params.issubset(
                        t.required_params | t.optional_params
                    ):
                        continue
                    matching.append(s)
                    break
        return matching

    def record_probe(
        self,
        server_id: str,
        success: bool,
        latency_ms: float,
        timestamp: Optional[float] = None,
    ) -> HealthStatus:
        """Record health probe response and update stateful health transitions."""
        if server_id not in self._servers:
            raise KeyError(f"Server {server_id} not registered")

        rec = self._health[server_id]
        rec.total_probes += 1
        rec.last_probe_time = time.time() if timestamp is None else float(timestamp)

        if success:
            rec.consecutive_successes += 1
            rec.consecutive_failures = 0
            rec.latencies_ms.append(max(0.0, float(latency_ms)))
            if len(rec.latencies_ms) > self.latency_window_size:
                rec.latencies_ms.pop(0)

            rec.status = HealthStatus.HEALTHY
        else:
            rec.consecutive_failures += 1
            rec.consecutive_successes = 0

            if rec.consecutive_failures >= self.failure_threshold:
                rec.status = HealthStatus.FAILING
            elif rec.consecutive_failures >= self.degrade_threshold:
                rec.status = HealthStatus.DEGRADED

        return rec.status

    def get_health_metrics(self, server_id: str) -> Dict[str, Any]:
        """Compute latency percentiles (p50, p95, p99) and status summary."""
        if server_id not in self._health:
            raise KeyError(f"Server {server_id} not registered")

        rec = self._health[server_id]
        lats = sorted(rec.latencies_ms)
        n = len(lats)

        def percentile(p: float) -> float:
            if not lats:
                return 0.0
            idx = int(math.ceil(p * n)) - 1
            return round(lats[max(0, min(idx, n - 1))], 2)

        return {
            "server_id": server_id,
            "status": rec.status.value,
            "total_probes": rec.total_probes,
            "consecutive_failures": rec.consecutive_failures,
            "p50_latency_ms": percentile(0.50),
            "p95_latency_ms": percentile(0.95),
            "p99_latency_ms": percentile(0.99),
        }
