"""Tests for atlas_session_rotary."""
import sys
sys.path.insert(0, "scripts")
from atlas_session_rotary import AtlasSessionRotary


def test_atlas_session_rotary():
    r = AtlasSessionRotary(max_size=2)
    r.push("s1"); r.push("s2"); r.push("s3")
    assert r.count() == 2
