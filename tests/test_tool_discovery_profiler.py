"""Tests for ToolDiscoveryProfiler."""
from scripts.tool_discovery_profiler import ToolDiscoveryProfiler


def test_tool_discovery_profiler():
    prof = ToolDiscoveryProfiler({"read": {"v": 1}, "write": {"v": 1}})
    res = prof.run_benchmark(["read", "write", "missing"], iterations=100)
    assert res["hits"] == 200
    assert res["ops_per_s"] > 0
