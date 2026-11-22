"""
Mcp-Server-Atlas - Catalog Latency Telemetry & Endpoint Availability Diagnostic Engine

Collects, aggregates, and audits real-time health metrics, latency percentiles (p50/p90/p99),
and uptime availability across community-indexed Model Context Protocol (MCP) servers.
Generates comprehensive diagnostic reports and Prometheus metrics.
"""

from __future__ import annotations

import math
import statistics
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class EndpointHealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"
    UNKNOWN = "UNKNOWN"


@dataclass
class ProbeResult:
    timestamp: float
    latency_ms: float
    success: bool
    status_code: Optional[int] = None
    error_message: Optional[str] = None


@dataclass
class ServerEndpointMetrics:
    server_id: str
    endpoint_url: str
    total_probes: int = 0
    successful_probes: int = 0
    failed_probes: int = 0
    consecutive_failures: int = 0
    recent_latencies: List[float] = field(default_factory=list)
    last_probe_time: Optional[float] = None
    last_status: EndpointHealthStatus = EndpointHealthStatus.UNKNOWN


class EndpointTelemetryCollector:
    """Thread-safe collector for MCP endpoint latency and availability tracking."""

    def __init__(self, max_history_per_server: int = 100) -> None:
        self.max_history = max(10, max_history_per_server)
        self._lock = threading.RLock()
        self._servers: Dict[str, ServerEndpointMetrics] = {}

    def register_endpoint(self, server_id: str, endpoint_url: str) -> None:
        """Initializes tracking for a catalog server."""
        with self._lock:
            sid = server_id.lower().strip()
            if sid not in self._servers:
                self._servers[sid] = ServerEndpointMetrics(
                    server_id=sid,
                    endpoint_url=endpoint_url.strip(),
                )

    def record_probe(
        self,
        server_id: str,
        latency_ms: float,
        success: bool,
        status_code: Optional[int] = None,
        error_message: Optional[str] = None,
        timestamp: Optional[float] = None,
    ) -> None:
        """Records an individual ping or JSON-RPC probe result."""
        with self._lock:
            sid = server_id.lower().strip()
            if sid not in self._servers:
                self.register_endpoint(sid, f"http://localhost/{sid}")

            metrics = self._servers[sid]
            now = timestamp or time.time()
            metrics.last_probe_time = now
            metrics.total_probes += 1

            if success:
                metrics.successful_probes += 1
                metrics.consecutive_failures = 0
                lat = max(0.0, float(latency_ms))
                metrics.recent_latencies.append(lat)
                if len(metrics.recent_latencies) > self.max_history:
                    metrics.recent_latencies.pop(0)
            else:
                metrics.failed_probes += 1
                metrics.consecutive_failures += 1

            # Update health status
            metrics.last_status = self._evaluate_health(metrics)

    def _evaluate_health(self, m: ServerEndpointMetrics) -> EndpointHealthStatus:
        if m.total_probes == 0:
            return EndpointHealthStatus.UNKNOWN

        if m.consecutive_failures >= 3:
            return EndpointHealthStatus.DOWN

        availability = (m.successful_probes / m.total_probes) * 100.0
        if availability < 80.0:
            return EndpointHealthStatus.DOWN

        if not m.recent_latencies:
            return EndpointHealthStatus.DOWN

        avg_lat = statistics.mean(m.recent_latencies)
        if availability < 95.0 or avg_lat > 1000.0:
            return EndpointHealthStatus.DEGRADED

        return EndpointHealthStatus.HEALTHY

    def get_server_stats(self, server_id: str) -> Optional[Dict[str, Any]]:
        """Computes statistical metrics (p50, p90, p99, jitter, availability)."""
        with self._lock:
            sid = server_id.lower().strip()
            if sid not in self._servers:
                return None

            m = self._servers[sid]
            if m.total_probes == 0:
                return {
                    "server_id": sid,
                    "endpoint_url": m.endpoint_url,
                    "status": EndpointHealthStatus.UNKNOWN.value,
                    "total_probes": 0,
                    "availability_pct": 0.0,
                }

            avail = round((m.successful_probes / m.total_probes) * 100.0, 2)
            latencies = sorted(m.recent_latencies)

            if latencies:
                p50 = round(statistics.median(latencies), 2)
                p90 = round(latencies[int(math.ceil(0.90 * len(latencies))) - 1], 2)
                p99 = round(latencies[int(math.ceil(0.99 * len(latencies))) - 1], 2)
                mean_lat = round(statistics.mean(latencies), 2)
                jitter = round(statistics.stdev(latencies), 2) if len(latencies) >= 2 else 0.0
            else:
                p50 = p90 = p99 = mean_lat = jitter = 0.0

            return {
                "server_id": sid,
                "endpoint_url": m.endpoint_url,
                "status": m.last_status.value,
                "total_probes": m.total_probes,
                "successful_probes": m.successful_probes,
                "failed_probes": m.failed_probes,
                "availability_pct": avail,
                "latency_mean_ms": mean_lat,
                "latency_p50_ms": p50,
                "latency_p90_ms": p90,
                "latency_p99_ms": p99,
                "jitter_ms": jitter,
            }

    def generate_diagnostic_summary(self) -> str:
        """Renders Markdown diagnostic table for all tracked endpoints."""
        with self._lock:
            lines = [
                "# MCP Server Atlas - Catalog Endpoint Availability Diagnostic",
                "",
                f"- **Tracked Servers**: {len(self._servers)}",
                "",
                "| Server ID | Status | Availability | p50 (ms) | p90 (ms) | p99 (ms) | Jitter |",
                "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
            ]

            for sid in sorted(self._servers.keys()):
                stats = self.get_server_stats(sid)
                if not stats:
                    continue
                lines.append(
                    f"| `{stats['server_id']}` | **{stats['status']}** | {stats['availability_pct']:.1f}% | "
                    f"{stats['latency_p50_ms']} | {stats['latency_p90_ms']} | {stats['latency_p99_ms']} | {stats['jitter_ms']} |"
                )

            lines.append("")
            return "\n".join(lines)

    def export_prometheus_metrics(self) -> str:
        """Renders metrics in standard Prometheus exposition format."""
        with self._lock:
            lines = [
                "# HELP mcp_endpoint_availability_ratio Endpoint availability percentage",
                "# TYPE mcp_endpoint_availability_ratio gauge",
            ]
            for sid, m in sorted(self._servers.items()):
                avail = (m.successful_probes / max(1, m.total_probes)) * 100.0
                lines.append(f'mcp_endpoint_availability_ratio{{server="{sid}"}} {avail:.2f}')

            lines.extend([
                "# HELP mcp_endpoint_latency_p90_ms 90th percentile latency in milliseconds",
                "# TYPE mcp_endpoint_latency_p90_ms gauge",
            ])
            for sid in sorted(self._servers.keys()):
                stats = self.get_server_stats(sid)
                if stats:
                    lines.append(f'mcp_endpoint_latency_p90_ms{{server="{sid}"}} {stats["latency_p90_ms"]}')

            return "\n".join(lines) + "\n"

    def reset(self) -> None:
        with self._lock:
            self._servers.clear()
