"""
Unit and regression test suite for MCP Transport & Tool Telemetry Engine.
"""

import pytest
from scripts.transport_telemetry import (
    ConnectionHealthRecord,
    ServerToolSummary,
    ToolExecutionEvent,
    TransportHealthState,
    TransportTelemetryEngine,
    TransportType,
)


def test_transport_telemetry_initialization():
    engine = TransportTelemetryEngine(max_p90_latency_ms=500.0, max_error_rate=0.08)
    assert engine.max_p90_latency_ms == 500.0
    assert engine.max_error_rate == 0.08
    assert len(engine.connections) == 0
    assert len(engine.events) == 0


def test_record_connection_state_and_drop_tracking():
    engine = TransportTelemetryEngine()

    # Initial connect
    conn = engine.record_connection_state(
        server_id="github-mcp",
        transport=TransportType.STDIO,
        state=TransportHealthState.CONNECTED,
        ping_latency_ms=12.5,
    )
    assert conn.state == TransportHealthState.CONNECTED
    assert conn.total_drops == 0
    assert conn.last_ping_latency_ms == 12.5

    # Unexpected drop
    conn_dropped = engine.record_connection_state(
        server_id="github-mcp",
        transport=TransportType.STDIO,
        state=TransportHealthState.DISCONNECTED,
    )
    assert conn_dropped.total_drops == 1

    # Reconnect attempt
    conn_rec = engine.record_connection_state(
        server_id="github-mcp",
        transport=TransportType.STDIO,
        state=TransportHealthState.RECONNECTING,
    )
    assert conn_rec.total_reconnects == 1


def test_record_tool_call_and_latency_aggregation():
    engine = TransportTelemetryEngine()

    ev1 = engine.record_tool_call("atlas-fs", "read_file", TransportType.STDIO, 15.0, True)
    assert ev1.tool_name == "read_file"
    assert ev1.success is True

    ev2 = engine.record_tool_call("atlas-fs", "read_file", TransportType.STDIO, 25.0, True)
    ev3 = engine.record_tool_call("atlas-fs", "read_file", TransportType.STDIO, 200.0, False, error_code=-32603)
    assert ev3.error_code == -32603

    stats = engine.tool_stats[("atlas-fs", "read_file")]
    assert stats.total_calls == 3
    assert stats.successful_calls == 2
    assert stats.failed_calls == 1
    assert stats.error_rate == 0.3333
    # Mean latency = (15 + 25 + 200) / 3 = 80.0
    assert stats.mean_latency_ms == 80.0


def test_server_tool_summary_p90_percentile():
    summary = ServerToolSummary(server_id="srv", tool_name="tool")
    assert summary.p90_latency_ms == 0.0

    summary.latencies_ms = [50.0]
    assert summary.p90_latency_ms == 50.0

    summary.latencies_ms = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    # 90th percentile = index int(10 * 0.90) = 9 -> sorted_lats[9] = 100.0
    assert summary.p90_latency_ms == 100.0


def test_evaluate_sla_breaches():
    engine = TransportTelemetryEngine(max_p90_latency_ms=100.0, max_error_rate=0.10)

    # Tool 1: Nominal (10 calls, all success, 15ms latency)
    for _ in range(10):
        engine.record_tool_call("srv1", "fast_tool", TransportType.STDIO, 15.0, True)

    # Tool 2: High error rate (6 successes, 4 failures = 40% error rate > 10%)
    for _ in range(6):
        engine.record_tool_call("srv1", "error_tool", TransportType.STDIO, 20.0, True)
    for _ in range(4):
        engine.record_tool_call("srv1", "error_tool", TransportType.STDIO, 25.0, False)

    # Tool 3: High latency (10 calls, all success, 250ms latency > 100ms ceiling)
    for _ in range(10):
        engine.record_tool_call("srv2", "slow_tool", TransportType.SSE, 250.0, True)

    # Tool 4: Too few samples (< 5), should be ignored
    engine.record_tool_call("srv3", "new_tool", TransportType.WEBSOCKET, 500.0, False)

    breaches = engine.evaluate_sla_breaches()
    breach_keys = {(b["server_id"], b["tool_name"]): b for b in breaches}

    assert ("srv1", "fast_tool") not in breach_keys
    assert ("srv3", "new_tool") not in breach_keys
    assert ("srv1", "error_tool") in breach_keys
    assert any("Error rate" in r for r in breach_keys[("srv1", "error_tool")]["reasons"])
    assert ("srv2", "slow_tool") in breach_keys
    assert any("P90 latency" in r for r in breach_keys[("srv2", "slow_tool")]["reasons"])


def test_export_prometheus_metrics():
    engine = TransportTelemetryEngine()
    engine.record_connection_state("node-server", TransportType.STDIO, TransportHealthState.CONNECTED)
    engine.record_tool_call("node-server", "search", TransportType.STDIO, 45.0, True)

    prom_text = engine.export_prometheus_metrics()
    assert "mcp_tool_invocations_total" in prom_text
    assert 'server_id="node-server"' in prom_text
    assert 'tool="search"' in prom_text
    assert "mcp_transport_connection_state" in prom_text


def test_generate_diagnostic_report_and_reset():
    engine = TransportTelemetryEngine()
    engine.record_connection_state("local-fs", TransportType.STDIO, TransportHealthState.CONNECTED, 2.5)
    engine.record_tool_call("local-fs", "list_dir", TransportType.STDIO, 8.0, True)

    report = engine.generate_diagnostic_report()
    assert "Mcp-Server-Atlas - Transport & Tool Telemetry Diagnostic" in report
    assert "local-fs" in report
    assert "list_dir" in report
    assert "Transport Connection Status" in report

    engine.reset()
    assert len(engine.connections) == 0
    assert len(engine.tool_stats) == 0
    assert len(engine.events) == 0
