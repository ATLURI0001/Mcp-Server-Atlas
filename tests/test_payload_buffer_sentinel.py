import pytest
import json
from scripts.payload_buffer_sentinel import (
    PayloadBufferSentinel,
    PayloadSentinelError,
    ViolationType,
)


def test_valid_payload_parsing_and_inspection():
    sentinel = PayloadBufferSentinel(
        max_payload_bytes=10000,
        max_depth=5,
        max_keys_per_object=20,
        max_array_length=50,
        max_string_length=1000,
    )
    raw = json.dumps({
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "lookup_route",
            "arguments": {"asn": 64500, "tags": ["prod", "edge"]},
        },
        "id": 1,
    })

    parsed, inspection = sentinel.sanitize_and_parse(raw)
    assert inspection.is_safe is True
    assert inspection.max_observed_depth == 5
    assert inspection.total_nodes > 5
    assert parsed["method"] == "tools/call"


def test_raw_payload_too_large_rejection():
    sentinel = PayloadBufferSentinel(max_payload_bytes=50)
    raw_large = b"x" * 51

    with pytest.raises(PayloadSentinelError) as exc_info:
        sentinel.inspect_raw_bytes(raw_large)
    assert exc_info.value.violation == ViolationType.PAYLOAD_TOO_LARGE


def test_excessive_nesting_depth_rejection():
    sentinel = PayloadBufferSentinel(max_depth=4)

    # Build depth = 6 nested dict
    nested = {"a": {"b": {"c": {"d": {"e": "deep"}}}}}
    with pytest.raises(PayloadSentinelError) as exc_info:
        sentinel.validate_payload(nested)
    assert exc_info.value.violation == ViolationType.EXCESSIVE_NESTING_DEPTH


def test_excessive_key_count_rejection():
    sentinel = PayloadBufferSentinel(max_keys_per_object=5)
    wide_obj = {f"k{i}": i for i in range(10)}

    with pytest.raises(PayloadSentinelError) as exc_info:
        sentinel.validate_payload(wide_obj)
    assert exc_info.value.violation == ViolationType.EXCESSIVE_KEY_COUNT


def test_excessive_array_length_rejection():
    sentinel = PayloadBufferSentinel(max_array_length=5)
    big_array = [1, 2, 3, 4, 5, 6]

    with pytest.raises(PayloadSentinelError) as exc_info:
        sentinel.validate_payload(big_array)
    assert exc_info.value.violation == ViolationType.EXCESSIVE_ARRAY_LENGTH


def test_string_length_exceeded_rejection():
    sentinel = PayloadBufferSentinel(max_string_length=20)
    payload = {"msg": "A" * 25}

    with pytest.raises(PayloadSentinelError) as exc_info:
        sentinel.validate_payload(payload)
    assert exc_info.value.violation == ViolationType.STRING_LENGTH_EXCEEDED


def test_invalid_json_encoding_rejection():
    sentinel = PayloadBufferSentinel()
    with pytest.raises(PayloadSentinelError) as exc_info:
        sentinel.sanitize_and_parse("{bad-json-syntax")
    assert exc_info.value.violation == ViolationType.INVALID_JSON_ENCODING
