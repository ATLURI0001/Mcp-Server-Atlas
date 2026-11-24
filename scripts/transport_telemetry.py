"""
Mcp-Server-Atlas - Tool Execution Latency & Transport Connection Health Telemetry.

Provides real-time observability across MCP transport connections (stdio, sse, ws, http),
tracks tool execution latency percentiles (P50/P90/P99), monitors connection drop rates,
and detects protocol SLA degradation.
"""

from __future__ import annotations

import statistics
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class TransportType(str, Enum):
    STDIO = "stdio"
    SSE = "sse"
    WEBSOCKET = "ws"
    HTTP = "http"


class TransportHealthState(str, Enum):
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    DISCONNECTED = "DISCONNECTED"
    RECONNECTING = "RECONNECTING"


@dataclass
class ToolExecutionEvent:
    """Discrete tool or RPC method invocation record."""
    server_id: str
    tool_name: str
    transport: TransportType
    duration_ms: float
    success: bool
    error_code: Optional[int] = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class ConnectionHealthRecord:
    """Metrics for an active or past transport connection."""
    server_id: str
    transport: TransportType
    state: TransportHealthState = TransportHealthState.DISCONNECTED
    active_since: float = 0.0
    total_reconnects: int = 0
    total_drops: int = 0
    last_ping_latency_ms: float = 0.0
    recent_ping_latencies: List[float] = field(default_factory=list)


@dataclass
class ServerToolSummary:
    """Aggregated tool metrics for a server/tool pair."""
    server_id: str
    tool_name: str
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    latencies_ms: List[float] = field(default_factory=list)

    @property
    def error_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return round(self.failed_calls / self.total_calls, 4)

    @property
    def mean_latency_ms(self) -> float:
        if not self.latencies_ms:
            return 0.0
        return round(statistics.mean(self.latencies_ms), 2)

    @property
    def p90_latency_ms(self) -> float:
        if not self.latencies_ms:
            return 0.0
        if len(self.latencies_ms) == 1:
            return round(self.latencies_ms[0], 2)
        sorted_lats = sorted(self.latencies_ms)
        idx = int(len(sorted_lats) * 0.90)
        return round(sorted_lats[min(idx, len(sorted_lats) - 1)], 2)


class TransportTelemetryEngine:
    """
    Thread-safe observability engine for MCP transport layers and tool latency tracking.
    """

    def __init__(
        self,
        max_p90_latency_ms: float = 1000.0,
        max_error_rate: float = 0.05,
    ) -> None:
        self.max_p90_latency_ms = max(10.0, float(max_p90_latency_ms))
        self.max_error_rate = max(0.01, min(1.0, float(max_error_rate)))
        self._lock = threading.RLock()

        self.connections: Dict[Tuple[str, str], ConnectionHealthRecord] = {}
        self.tool_stats: Dict[Tuple[str, str], ServerToolSummary] = {}
        self.events: List[ToolExecutionEvent] = []

    def record_connection_state(
        self,
        server_id: str,
        transport: TransportType | str,
        state: TransportHealthState | str,
        ping_latency_ms: Optional[float] = None,
    ) -> ConnectionHealthRecord:
        """Updates connection state and ping metrics."""
        sid = str(server_id or "").strip()
        t_type = TransportType(transport) if isinstance(transport, str) else transport
        h_state = TransportHealthState(state) if isinstance(state, str) else state

        key = (sid, t_type.value)
        with self._lock:
            if key not in self.connections:
                self.connections[key] = ConnectionHealthRecord(server_id=sid, transport=t_type)

            rec = self.connections[key]
            old_state = rec.state
            rec.state = h_state

            now = time.time()
            if h_state == TransportHealthState.CONNECTED:
                if old_state != TransportHealthState.CONNECTED:
                    rec.active_since = now
            elif h_state == TransportHealthState.DISCONNECTED:
                if old_state == TransportHealthState.CONNECTED:
                    rec.total_drops += 1
            elif h_state == TransportHealthState.RECONNECTING:
                rec.total_reconnects += 1

            if ping_latency_ms is not None:
                lat = max(0.0, float(ping_latency_ms))
                rec.last_ping_latency_ms = lat
                rec.recent_ping_latencies.append(lat)
                if len(rec.recent_ping_latencies) > 50:
                    rec.recent_ping_latencies.pop(0)

            return rec

    def record_tool_call(
        self,
        server_id: str,
        tool_name: str,
        transport: TransportType | str,
        duration_ms: float,
        success: bool,
        error_code: Optional[int] = None,
    ) -> ToolExecutionEvent:
        """Records a single tool execution invocation."""
        sid = str(server_id or "").strip()
        tname = str(tool_name or "").strip()
        t_type = TransportType(transport) if isinstance(transport, str) else transport
        dur = max(0.0, float(duration_ms))

        event = ToolExecutionEvent(
            server_id=sid,
            tool_name=tname,
            transport=t_type,
            duration_ms=dur,
            success=bool(success),
            error_code=error_code,
        )

        key = (sid, tname)
        with self._lock:
            self.events.append(event)
            if key not in self.tool_stats:
                self.tool_stats[key] = ServerToolSummary(server_id=sid, tool_name=tname)

            stats = self.tool_stats[key]
            stats.total_calls += 1
            if success:
                stats.successful_calls += 1
            else:
                stats.failed_calls += 1

            stats.latencies_ms.append(dur)
            if len(stats.latencies_ms) > 500:
                stats.latencies_ms.pop(0)

        return event

    def evaluate_sla_breaches(self) -> List[Dict[str, Any]]:
        """Identifies servers or tools violating latency or reliability SLAs."""
        breaches = []
        with self._lock:
            for (sid, tname), stats in self.tool_stats.items():
                if stats.total_calls < 5:
                    continue  # Require minimal sample size

                err_rate = stats.error_rate
                p90 = stats.p90_latency_ms

                reasons = []
                if err_rate > self.max_error_rate:
                    reasons.append(f"Error rate {err_rate:.2%} > threshold {self.max_error_rate:.2%}")
                if p90 > self.max_p90_latency_ms:
                    reasons.append(f"P90 latency {p90}ms > ceiling {self.max_p90_latency_ms}ms")

                if reasons:
                    breaches.append({
                        "server_id": sid,
                        "tool_name": tname,
                        "error_rate": err_rate,
                        "p90_latency_ms": p90,
                        "total_calls": stats.total_calls,
                        "reasons": reasons,
                    })

        return breaches

    def export_prometheus_metrics(self) -> str:
        """Exports metrics in Prometheus OpenMetrics exposition text format."""
        lines = [
            "# HELP mcp_tool_invocations_total Total number of MCP tool invocations",
            "# TYPE mcp_tool_invocations_total counter",
        ]

        with self._lock:
            for (sid, tname), stats in self.tool_stats.items():
                lines.append(
                    f'mcp_tool_invocations_total{{server_id="{sid}",tool="{tname}",status="success"}} {stats.successful_calls}'
                )
                lines.append(
                    f'mcp_tool_invocations_total{{server_id="{sid}",tool="{tname}",status="error"}} {stats.failed_calls}'
                )

            lines.extend([
                "# HELP mcp_tool_p90_duration_ms 90th percentile tool execution duration in milliseconds",
                "# TYPE mcp_tool_p90_duration_ms gauge",
            ])
            for (sid, tname), stats in self.tool_stats.items():
                lines.append(
                    f'mcp_tool_p90_duration_ms{{server_id="{sid}",tool="{tname}"}} {stats.p90_latency_ms}'
                )

            lines.extend([
                "# HELP mcp_transport_connection_state Active connection state (1=CONNECTED, 0=OTHER)",
                "# TYPE mcp_transport_connection_state gauge",
            ])
            for (sid, t_val), conn in self.connections.items():
                is_connected = 1 if conn.state == TransportHealthState.CONNECTED else 0
                lines.append(
                    f'mcp_transport_connection_state{{server_id="{sid}",transport="{t_val}"}} {is_connected}'
                )

        return "\n".join(lines)

    def generate_diagnostic_report(self) -> str:
        """Generates a structured Markdown diagnostic table."""
        with self._lock:
            active_conns = sum(
                1 for c in self.connections.values() if c.state == TransportHealthState.CONNECTED
            )
            total_events = len(self.events)
            breaches = self.evaluate_sla_breaches()
            breached_keys = {(b["server_id"], b["tool_name"]) for b in breaches}

            lines = [
                "# Mcp-Server-Atlas - Transport & Tool Telemetry Diagnostic",
                "",
                f"- **Active Transport Connections:** `{active_conns}`",
                f"- **Total Invocations Recorded:** `{total_events}`",
                f"- **Monitored Tool Endpoints:** `{len(self.tool_stats)}`",
                f"- **SLA Breaches Detected:** `{len(breaches)}`",
                "",
                "## Tool Execution Telemetry Table",
                "| Server ID | Tool Name | Calls | Success | Failures | Error Rate | Mean Latency | P90 Latency | Status |",
                "|---|---|---|---|---|---|---|---|---|",
            ]

            for (sid, tname), stats in sorted(self.tool_stats.items()):
                status_badge = "❌ BREACH" if (sid, tname) in breached_keys else "✅ NOMINAL"
                lines.append(
                    f"| `{sid}` | `{tname}` | {stats.total_calls} | {stats.successful_calls} | "
                    f"{stats.failed_calls} | {stats.error_rate:.2%} | {stats.mean_latency_ms}ms | "
                    f"{stats.p90_latency_ms}ms | {status_badge} |"
                )

            if self.connections:
                lines.extend([
                    "",
                    "## Transport Connection Status",
                    "| Server ID | Transport | State | Reconnects | Drops | Last Ping |",
                    "|---|---|---|---|---|---|",
                ])
                for (sid, t_val), conn in sorted(self.connections.items()):
                    lines.append(
                        f"| `{sid}` | `{conn.transport.value}` | `{conn.state.value}` | "
                        f"{conn.total_reconnects} | {conn.total_drops} | {conn.last_ping_latency_ms:.1f}ms |"
                    )

            return "\n".join(lines)

    def reset(self) -> None:
        """Clears all accumulated connection and tool telemetry."""
        with self._lock:
            self.connections.clear()
            self.tool_stats.clear()
            self.events.clear()
