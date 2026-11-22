"""Unit tests for JSON-RPC Transport Framing Codec and Content-Length Hardener."""

import json
import pytest
from transport_framing import FramingError, TransportFramingCodec


def test_roundtrip_encode_decode() -> None:
    codec = TransportFramingCodec()
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {},
    }

    encoded = codec.encode_frame(payload)
    assert b"Content-Length: " in encoded
    assert b"Content-Type: application/vscode-jsonrpc" in encoded

    frames = codec.feed_bytes(encoded)
    assert len(frames) == 1
    assert frames[0].payload == payload
    assert frames[0].content_length == len(frames[0].body_bytes)


def test_multibyte_utf8_character_exact_byte_length() -> None:
    codec = TransportFramingCodec()
    # Emojis and multi-byte kanji characters: character count is much smaller than byte count
    payload = {
        "jsonrpc": "2.0",
        "method": "echo",
        "text": "Hello 🚀 世界 こんにちは 🌟",
    }

    encoded = codec.encode_frame(payload)
    frames = codec.feed_bytes(encoded)
    assert len(frames) == 1
    assert frames[0].payload["text"] == "Hello 🚀 世界 こんにちは 🌟"
    # Ensure Content-Length matches exact UTF-8 encoded bytes
    expected_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert frames[0].content_length == len(expected_bytes)


def test_fragmented_streaming_chunks() -> None:
    codec = TransportFramingCodec()
    payload = {"jsonrpc": "2.0", "result": {"status": "ok"}}
    encoded = codec.encode_frame(payload)

    # Feed 7 bytes at a time to simulate fragmented TCP stream
    chunk_size = 7
    all_frames = []
    for i in range(0, len(encoded), chunk_size):
        chunk = encoded[i : i + chunk_size]
        frames = codec.feed_bytes(chunk)
        all_frames.extend(frames)

    assert len(all_frames) == 1
    assert all_frames[0].payload == payload


def test_pipelined_multiple_frames_in_single_chunk() -> None:
    codec = TransportFramingCodec()
    msg1 = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    msg2 = {"jsonrpc": "2.0", "id": 2, "method": "pong"}

    combined = codec.encode_frame(msg1) + codec.encode_frame(msg2)
    frames = codec.feed_bytes(combined)

    assert len(frames) == 2
    assert frames[0].payload["method"] == "ping"
    assert frames[1].payload["method"] == "pong"


def test_missing_content_length_error() -> None:
    codec = TransportFramingCodec()
    malformed = b"Content-Type: text/plain\r\n\r\n{\"jsonrpc\": \"2.0\"}"

    with pytest.raises(FramingError, match="Missing mandatory 'Content-Length' header"):
        codec.feed_bytes(malformed)


def test_content_length_exceeds_maximum_boundary() -> None:
    codec = TransportFramingCodec(max_frame_bytes=1024)
    # Header claims 5000 bytes
    huge_header = b"Content-Length: 5000\r\n\r\n"

    with pytest.raises(FramingError, match="exceeds maximum boundary"):
        codec.feed_bytes(huge_header)


def test_malformed_json_body_error() -> None:
    codec = TransportFramingCodec()
    bad_body = b"not-a-valid-json-object"
    header = f"Content-Length: {len(bad_body)}\r\n\r\n".encode("ascii")

    with pytest.raises(FramingError, match="Malformed JSON-RPC payload"):
        codec.feed_bytes(header + bad_body)
