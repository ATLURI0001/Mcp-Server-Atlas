"""Tests for atlas_endpoint_contract."""
import sys
sys.path.insert(0, "scripts")
from atlas_endpoint_contract import AtlasEndpointContract


def test_atlas_endpoint_contract():
    c = AtlasEndpointContract(["GET", "POST"])
    assert c.validate("get") is True
    assert c.validate("DELETE") is False
