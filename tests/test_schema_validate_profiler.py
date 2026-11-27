"""Tests for schema_validate_profiler."""
from scripts.schema_validate_profiler import benchmark_schema_validate


def test_schema_validate_profiler():
    ops = benchmark_schema_validate(["id", "query"], {"id": 1, "query": "hi"}, iterations=100)
    assert ops > 0
