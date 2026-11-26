"""Tests for RegistrySyncCircuitBreaker."""
import pytest
from scripts.registry_sync_circuit_breaker import (
    RegistryCircuitOpenError,
    RegistrySyncCircuitBreaker,
)


def test_registry_sync_circuit_breaker():
    cb = RegistrySyncCircuitBreaker(threshold=2, cooldown_s=5.0)
    with pytest.raises(RuntimeError):
        cb.call(lambda: (_ for _ in ()).throw(RuntimeError("sync fail")))
    with pytest.raises(RuntimeError):
        cb.call(lambda: (_ for _ in ()).throw(RuntimeError("sync fail")))
    with pytest.raises(RegistryCircuitOpenError):
        cb.call(lambda: "ok")
