"""
Unit tests for Mcp-Server-Atlas Multi-Transport Session Multiplexer & Framing Protocol Guard.
"""

import sys
from pathlib import Path
import time
import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from session_multiplexer import (
    FramingProtocolGuard,
    SessionMultiplexer,
    PayloadTooLargeError,
)


def test_framing_length_prefixed_roundtrip():
    guard = FramingProtocolGuard(max_frame_size_bytes=1024)
    payload = b'{"jsonrpc":"2.0","method":"ping","id":1}'

    encoded = guard.encode_length_prefixed(payload)
    assert len(encoded) == 4 + len(payload)

    # Incomplete buffer
    buffer = bytearray(encoded[:10])
    frame, consumed = guard.decode_length_prefixed(buffer)
    assert frame is None
    assert consumed == 0

    # Complete buffer
    buffer.extend(encoded[10:])
    frame, consumed = guard.decode_length_prefixed(buffer)
    assert frame == payload
    assert consumed == len(encoded)


def test_framing_payload_too_large_rejection():
    guard = FramingProtocolGuard(max_frame_size_bytes=100)
    oversized = b"x" * 150

    with pytest.raises(PayloadTooLargeError):
        guard.encode_length_prefixed(oversized)

    # Decode crafted header declaring 500 bytes
    import struct
    evil_header = bytearray(struct.pack(">I", 500) + b"dummy")
    with pytest.raises(PayloadTooLargeError):
        guard.decode_length_prefixed(evil_header)


def test_framing_newline_delimited():
    guard = FramingProtocolGuard()
    raw = bytearray(b'{"id":1}\n{"id":2}\n')

    msg1, consumed1 = guard.decode_newline_delimited(raw)
    assert msg1 == '{"id":1}'
    del raw[:consumed1]

    msg2, consumed2 = guard.decode_newline_delimited(raw)
    assert msg2 == '{"id":2}'
    del raw[:consumed2]

    msg3, consumed3 = guard.decode_newline_delimited(raw)
    assert msg3 is None
    assert consumed3 == 0


def test_session_multiplexer_lifecycle_and_eviction():
    sm = SessionMultiplexer(idle_timeout_sec=0.1, max_sessions=2)

    s1 = sm.create_session("sess_1", "stdio", {"client": "test"})
    assert s1.session_id == "sess_1"
    assert sm.get_session("sess_1") is not None

    s2 = sm.create_session("sess_2", "sse")
    assert sm.get_session("sess_2") is not None

    # Capacity overflow
    with pytest.raises(RuntimeError):
        sm.create_session("sess_3", "websocket")

    # Route message
    assert sm.route_message("sess_1", {"type": "ping"}) is True
    assert s1.message_count == 1

    # Route to non-existent session
    assert sm.route_message("sess_nonexistent", {}) is False

    # Eviction past idle timeout
    time.sleep(0.12)
    evicted = sm.evict_idle_sessions()
    assert "sess_1" in evicted
    assert "sess_2" in evicted
    assert len(sm.sessions) == 0
