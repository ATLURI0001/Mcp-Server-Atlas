"""Tests for TransportCircuitBreaker."""

import pytest
import time
from scripts.transport_circuit_breaker import (
    CircuitBreakerOpenError,
    CircuitState,
    TransportCircuitBreaker,
)


def test_nominal_execution():
    breaker = TransportCircuitBreaker(failure_threshold=3, recovery_timeout_sec=1.0)
    assert breaker.state == CircuitState.CLOSED

    res, fallback = breaker.execute("ping", lambda: "pong")
    assert res == "pong"
    assert fallback is False

    metrics = breaker.get_metrics()
    assert metrics["total_calls"] == 1
    assert metrics["fallback_calls"] == 0
    assert metrics["consecutive_failures"] == 0


def test_failure_threshold_tripping():
    breaker = TransportCircuitBreaker(failure_threshold=2, recovery_timeout_sec=5.0)

    def failing():
        raise ConnectionResetError("Broken pipe")

    with pytest.raises(ConnectionResetError):
        breaker.execute("failing_op", failing)

    assert breaker.state == CircuitState.CLOSED
    assert breaker.get_metrics()["consecutive_failures"] == 1

    with pytest.raises(ConnectionResetError):
        breaker.execute("failing_op", failing)

    # Tripped to OPEN
    assert breaker.state == CircuitState.OPEN
    metrics = breaker.get_metrics()
    assert metrics["state"] == "OPEN"
    assert "Broken pipe" in metrics["last_failure_reason"]

    # In OPEN state without fallback handler -> CircuitBreakerOpenError
    with pytest.raises(CircuitBreakerOpenError) as exc_info:
        breaker.execute("next_op", lambda: "ok")
    assert exc_info.value.retry_after > 0


def test_fallback_handler_delegation():
    def fallback(action, *args, **kwargs):
        return {"status": "degraded", "action": action, "cached": True}

    breaker = TransportCircuitBreaker(failure_threshold=1, fallback_handler=fallback)

    # Executing failing function delegates to fallback
    res, used_fallback = breaker.execute("query_tools", lambda: 1 / 0)
    assert used_fallback is True
    assert res["status"] == "degraded"
    assert res["action"] == "query_tools"
    assert breaker.state == CircuitState.OPEN

    # Subsequent call while OPEN also invokes fallback seamlessly
    res2, used_fallback2 = breaker.execute("query_tools", lambda: "never reached")
    assert used_fallback2 is True
    assert res2["cached"] is True
    assert breaker.get_metrics()["fallback_calls"] == 2


def test_heartbeat_monitoring():
    breaker = TransportCircuitBreaker(failure_threshold=1, heartbeat_timeout_sec=0.1)

    now = 1000.0
    breaker.record_heartbeat("session-1", timestamp=now)

    assert breaker.check_heartbeat("session-1", current_time=now + 0.05) is True
    assert breaker.state == CircuitState.CLOSED

    # After timeout
    assert breaker.check_heartbeat("session-1", current_time=now + 0.15) is False
    assert breaker.state == CircuitState.OPEN
    assert "Heartbeat timeout" in breaker.get_metrics()["last_failure_reason"]


def test_half_open_recovery():
    breaker = TransportCircuitBreaker(
        failure_threshold=1,
        recovery_timeout_sec=0.05,
        half_open_max_trials=2,
    )

    breaker.record_failure("test fail")
    assert breaker.state == CircuitState.OPEN

    # Sleep past recovery timeout
    time.sleep(0.06)
    assert breaker.state == CircuitState.HALF_OPEN

    # 1st success in HALF_OPEN
    breaker.record_success()
    assert breaker.state == CircuitState.HALF_OPEN

    # 2nd success in HALF_OPEN recovers to CLOSED
    breaker.record_success()
    assert breaker.state == CircuitState.CLOSED
