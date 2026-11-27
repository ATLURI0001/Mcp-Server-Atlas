"""Tests for atlas_query_profiler."""
import sys
sys.path.insert(0, "scripts")
from atlas_query_profiler import AtlasQueryProfiler


def test_atlas_query_profiler():
    p = AtlasQueryProfiler()
    p.record(12.5)
    p.record(30.0)
    assert p.max_ms() == 30.0
