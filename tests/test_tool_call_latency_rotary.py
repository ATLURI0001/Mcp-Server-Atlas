"""Tests for ToolCallLatencyRotary."""
from scripts.tool_call_latency_rotary import ToolCallLatencyRotary


def test_tool_call_latency_rotary():
    r = ToolCallLatencyRotary(capacity=2)
    r.record(10.0)
    r.record(20.0)
    r.record(40.0)
    assert r.avg_ms() == 30.0
