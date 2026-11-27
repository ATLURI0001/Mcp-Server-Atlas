"""Tests for StdioPipeCircuitBreaker."""
import pytest
from scripts.stdio_pipe_circuit_breaker import (
    StdioCircuitOpenError,
    StdioPipeCircuitBreaker,
)


def test_stdio_pipe_circuit_breaker():
    cb = StdioPipeCircuitBreaker(threshold=2, cooldown_s=5.0)
    with pytest.raises(BrokenPipeError):
        cb.call(lambda: (_ for _ in ()).throw(BrokenPipeError("eof")))
    with pytest.raises(BrokenPipeError):
        cb.call(lambda: (_ for _ in ()).throw(BrokenPipeError("eof")))
    with pytest.raises(StdioCircuitOpenError):
        cb.call(lambda: "ok")
