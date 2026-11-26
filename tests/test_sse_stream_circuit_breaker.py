from scripts.sse_stream_circuit_breaker import SseStreamCircuitBreaker, StreamState


def test_sse_circuit_breaker_reconnect_storm():
    cb = SseStreamCircuitBreaker(failure_threshold=2, recovery_threshold=2, cooldown_seconds=1.0)
    cid = "client-1"

    assert cb.allow_connect(cid, now=10.0) is True
    cb.record_disconnect(cid, clean=False, now=10.1)
    assert cb.allow_connect(cid, now=10.2) is True

    state = cb.record_disconnect(cid, clean=False, now=10.3)
    assert state == StreamState.OPEN
    assert cb.allow_connect(cid, now=10.5) is False

    # After cooldown -> HALF_OPEN -> CLOSED
    assert cb.allow_connect(cid, now=11.5) is True
    cb.record_disconnect(cid, clean=True, now=11.6)
    state = cb.record_disconnect(cid, clean=True, now=11.7)
    assert state == StreamState.CLOSED
