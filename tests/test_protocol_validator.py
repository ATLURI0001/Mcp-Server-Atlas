import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from protocol_validator import (
    EnvelopeType,
    McpErrorCode,
    ProtocolValidator,
    build_error_response,
    build_success_response,
)


def test_valid_request():
    validator = ProtocolValidator()
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": "req-42",
        "method": "tools/call",
        "params": {"name": "query_db", "arguments": {"sql": "SELECT 1"}},
    })
    res = validator.validate_raw(payload)
    assert res.is_valid is True
    assert res.envelope_type == EnvelopeType.REQUEST
    assert res.request_id == "req-42"
    assert res.method == "tools/call"
    assert res.error_code is None


def test_valid_notification():
    validator = ProtocolValidator()
    payload = json.dumps({
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
    })
    res = validator.validate_raw(payload)
    assert res.is_valid is True
    assert res.envelope_type == EnvelopeType.NOTIFICATION
    assert res.request_id is None
    assert res.method == "notifications/initialized"


def test_valid_response_and_builder():
    validator = ProtocolValidator()
    resp = build_success_response("req-101", {"content": [{"type": "text", "text": "pong"}]})
    res = validator.validate_parsed(resp)
    assert res.is_valid is True
    assert res.envelope_type == EnvelopeType.RESPONSE
    assert res.request_id == "req-101"


def test_valid_error_and_builder():
    validator = ProtocolValidator()
    err_resp = build_error_response(
        "req-99",
        McpErrorCode.METHOD_NOT_FOUND,
        "Unknown method requested",
        data={"hint": "Use tools/list"},
    )
    res = validator.validate_parsed(err_resp)
    assert res.is_valid is True
    assert res.envelope_type == EnvelopeType.ERROR
    assert res.request_id == "req-99"
    assert res.error_code == -32601
    assert res.details == {"hint": "Use tools/list"}


def test_parse_error():
    validator = ProtocolValidator()
    res = validator.validate_raw("{invalid json")
    assert res.is_valid is False
    assert res.error_code == McpErrorCode.PARSE_ERROR


def test_payload_size_limit():
    validator = ProtocolValidator(max_payload_bytes=64)
    big_payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping", "data": "A" * 100})
    res = validator.validate_raw(big_payload)
    assert res.is_valid is False
    assert res.error_code == McpErrorCode.PAYLOAD_TOO_LARGE


def test_invalid_jsonrpc_version():
    validator = ProtocolValidator()
    res = validator.validate_parsed({"jsonrpc": "1.0", "id": 1, "method": "ping"})
    assert res.is_valid is False
    assert res.error_code == McpErrorCode.INVALID_REQUEST
    assert "Unsupported jsonrpc" in (res.error_message or "")


def test_invalid_id_type():
    validator = ProtocolValidator()
    res = validator.validate_parsed({"jsonrpc": "2.0", "id": ["invalid", "id"], "method": "ping"})
    assert res.is_valid is False
    assert res.error_code == McpErrorCode.INVALID_REQUEST
    assert "Invalid 'id' type" in (res.error_message or "")


def test_method_not_found_in_whitelist():
    validator = ProtocolValidator(allowed_methods={"tools/list", "tools/call", "ping"})
    res = validator.validate_parsed({"jsonrpc": "2.0", "id": 1, "method": "secrets/steal"})
    assert res.is_valid is False
    assert res.error_code == McpErrorCode.METHOD_NOT_FOUND


def test_invalid_params_type():
    validator = ProtocolValidator()
    # RFC requires params to be structured (dict or list), not string/int
    res = validator.validate_parsed({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": "scalar_string"})
    assert res.is_valid is False
    assert res.error_code == McpErrorCode.INVALID_PARAMS


def test_batch_validation():
    validator = ProtocolValidator(max_batch_size=5)

    # Empty batch
    empty_res = validator.validate_parsed([])
    assert empty_res.is_valid is False
    assert empty_res.error_code == McpErrorCode.INVALID_REQUEST

    # Valid batch
    batch_valid = [
        {"jsonrpc": "2.0", "id": 1, "method": "ping"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    batch_res = validator.validate_parsed(batch_valid)
    assert batch_res.is_valid is True
    assert batch_res.envelope_type == EnvelopeType.BATCH
    assert batch_res.details["batch_size"] == 2

    # Batch exceeding max size
    overflow_batch = [{"jsonrpc": "2.0", "id": i, "method": "ping"} for i in range(10)]
    overflow_res = validator.validate_parsed(overflow_batch)
    assert overflow_res.is_valid is False
    assert "exceeds maximum limit" in (overflow_res.error_message or "")


def test_namespaced_method_enforcement():
    strict_validator = ProtocolValidator(require_namespaced_methods=True)
    res = strict_validator.validate_parsed({"jsonrpc": "2.0", "id": 1, "method": "unnamespaced"})
    assert res.is_valid is False
    assert res.error_code == McpErrorCode.INVALID_REQUEST
    assert "must be namespaced" in (res.error_message or "")
