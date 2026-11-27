"""Tests for SseReconnectRotary."""
from scripts.sse_reconnect_rotary import SseReconnectRotary


def test_sse_reconnect_rotary():
    r = SseReconnectRotary(capacity=2)
    r.record(1)
    r.record(3)
    r.record(5)
    assert r.avg_reconnects() == 4.0
