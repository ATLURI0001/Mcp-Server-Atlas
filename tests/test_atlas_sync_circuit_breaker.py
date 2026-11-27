"""Tests for atlas_sync_circuit_breaker."""
import sys
sys.path.insert(0, "scripts")
from atlas_sync_circuit_breaker import AtlasSyncCircuitBreaker


def test_atlas_sync_circuit_breaker():
    cb = AtlasSyncCircuitBreaker(threshold=2)
    assert cb.is_open() is False
    cb.record_failure(); cb.record_failure()
    assert cb.is_open() is True
