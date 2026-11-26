"""Tests for jsonrpc_parse_profiler."""
from scripts.jsonrpc_parse_profiler import benchmark_jsonrpc_parse


def test_jsonrpc_parse_profiler():
    ops = benchmark_jsonrpc_parse('{"jsonrpc":"2.0","id":1,"method":"tools/list"}', iterations=100)
    assert ops > 0
