"""Tests for atlas_cache_rotary."""
import sys
sys.path.insert(0, "scripts")
from atlas_cache_rotary import AtlasCacheRotary


def test_atlas_cache_rotary():
    r = AtlasCacheRotary(max_size=3)
    r.push("a"); r.push("b"); r.push("c"); r.push("d")
    assert r.count() == 3
    assert "a" not in r.latest()
