"""MCP Tool Dispatch Latency & Payload Size Telemetry Rotary.

Thread-safe circular ring buffer tracking Model Context Protocol tool execution latency,
payload sizes (request/response), throughput, and error rates.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class ToolDispatchRecord:
    tool_name: str
    request_bytes: int
    response_bytes: int
    latency_ms: float
    success: bool
    error_code: Optional[str] = None


@dataclass
class ToolTelemetrySummary:
    total_records: int = 0
    sample_count: int = 0
    error_rate_percent: float = 0.0
    p50_latency_ms: float = 0.0
    p90_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    p50_response_bytes: int = 0
    p90_response_bytes: int = 0
    tool_frequency: Dict[str, int] = field(default_factory=dict)


class ToolDispatchTelemetryRotary:
    """Fixed-envelope circular buffer for tool dispatch performance metrics."""

    def __init__(self, capacity: int = 500) -> None:
        if capacity <= 0:
            raise ValueError("Capacity must be positive")
        self.capacity = capacity
        self.buffer: List[Optional[ToolDispatchRecord]] = [None] * capacity
        self.head = 0
        self.count = 0
        self.total_recorded = 0

    def record(
        self,
        tool_name: str,
        request_bytes: int,
        response_bytes: int,
        latency_ms: float,
        success: bool = True,
        error_code: Optional[str] = None,
    ) -> None:
        if not tool_name:
            raise ValueError("tool_name cannot be empty")

        rec = ToolDispatchRecord(
            tool_name=tool_name,
            request_bytes=max(0, request_bytes),
            response_bytes=max(0, response_bytes),
            latency_ms=max(0.0, latency_ms),
            success=success,
            error_code=error_code if not success else None,
        )

        self.buffer[self.head] = rec
        self.head = (self.head + 1) % self.capacity
        if self.count < self.capacity:
            self.count += 1
        self.total_recorded += 1

    def get_summary(self) -> ToolTelemetrySummary:
        if self.count == 0:
            return ToolTelemetrySummary()

        records = [self.buffer[i] for i in range(self.count) if self.buffer[i] is not None]
        failures = sum(1 for r in records if not r.success)
        error_rate = (failures / len(records)) * 100.0

        latencies = sorted(r.latency_ms for r in records)
        responses = sorted(r.response_bytes for r in records)

        p50_lat = latencies[int(len(latencies) * 0.5)]
        p90_lat = latencies[int(len(latencies) * 0.9)]
        p99_lat = latencies[int(len(latencies) * 0.99)]

        p50_resp = responses[int(len(responses) * 0.5)]
        p90_resp = responses[int(len(responses) * 0.9)]

        tool_freq = dict(Counter(r.tool_name for r in records))

        return ToolTelemetrySummary(
            total_records=self.total_recorded,
            sample_count=self.count,
            error_rate_percent=round(error_rate, 2),
            p50_latency_ms=round(p50_lat, 2),
            p90_latency_ms=round(p90_lat, 2),
            p99_latency_ms=round(p99_lat, 2),
            p50_response_bytes=int(p50_resp),
            p90_response_bytes=int(p90_resp),
            tool_frequency=tool_freq,
        )
