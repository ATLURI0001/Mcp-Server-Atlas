"""MCP JSON-RPC 2.0 Protocol Validator and Envelope Resilience Engine.

Provides strict JSON-RPC 2.0 validation, standard MCP error mapping,
payload boundary guards, and response formatting for Model Context Protocol servers.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, Dict, List, Optional, Set, Union


class McpErrorCode(IntEnum):
    """Standard JSON-RPC 2.0 and MCP protocol error codes."""
    # Standard JSON-RPC 2.0 codes
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    # Protocol & Server-specific codes (-32000 to -32099)
    TOOL_EXECUTION_ERROR = -32000
    RESOURCE_NOT_FOUND = -32001
    SERVER_NOT_INITIALIZED = -32002
    PAYLOAD_TOO_LARGE = -32003
    RATE_LIMITED = -32004


STANDARD_ERROR_MESSAGES: Dict[int, str] = {
    McpErrorCode.PARSE_ERROR: "Parse error: Invalid JSON received",
    McpErrorCode.INVALID_REQUEST: "Invalid Request: Envelope structure does not conform to JSON-RPC 2.0",
    McpErrorCode.METHOD_NOT_FOUND: "Method not found: Requested RPC method does not exist",
    McpErrorCode.INVALID_PARAMS: "Invalid params: Method parameters failed schema validation",
    McpErrorCode.INTERNAL_ERROR: "Internal error: Server encountered an unexpected internal condition",
    McpErrorCode.TOOL_EXECUTION_ERROR: "Tool execution error: Tool invocation failed during execution",
    McpErrorCode.RESOURCE_NOT_FOUND: "Resource not found: Requested URI or resource is unavailable",
    McpErrorCode.SERVER_NOT_INITIALIZED: "Server not initialized: Must complete 'initialize' handshake first",
    McpErrorCode.PAYLOAD_TOO_LARGE: "Payload too large: Request body exceeds maximum allowed byte size",
    McpErrorCode.RATE_LIMITED: "Rate limited: Client exceeded request concurrency or throughput quota",
}


class EnvelopeType(str, Enum):
    """Classification of JSON-RPC 2.0 message envelopes."""
    REQUEST = "request"
    NOTIFICATION = "notification"
    RESPONSE = "response"
    ERROR = "error"
    BATCH = "batch"


METHOD_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]+(/[a-zA-Z0-9_.-]+)?$")


@dataclass
class ValidationResult:
    """Detailed validation outcome for a JSON-RPC 2.0 envelope."""
    is_valid: bool
    envelope_type: Optional[EnvelopeType] = None
    request_id: Optional[Union[str, int, None]] = None
    method: Optional[str] = None
    error_code: Optional[int] = None
    error_message: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert validation result to dictionary format."""
        return {
            "is_valid": self.is_valid,
            "envelope_type": self.envelope_type.value if self.envelope_type else None,
            "request_id": self.request_id,
            "method": self.method,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "details": self.details,
        }


class ProtocolValidator:
    """Validates incoming messages against JSON-RPC 2.0 and MCP specifications."""

    def __init__(
        self,
        max_payload_bytes: int = 4 * 1024 * 1024,  # 4 MiB
        max_batch_size: int = 50,
        allowed_methods: Optional[Set[str]] = None,
        require_namespaced_methods: bool = False,
    ):
        self.max_payload_bytes = max_payload_bytes
        self.max_batch_size = max_batch_size
        self.allowed_methods = allowed_methods
        self.require_namespaced_methods = require_namespaced_methods

    def validate_raw(self, raw_input: Union[str, bytes, bytearray]) -> ValidationResult:
        """Validate raw string or byte payload including parsing and size bounds."""
        if isinstance(raw_input, (bytes, bytearray)):
            byte_len = len(raw_input)
            if byte_len > self.max_payload_bytes:
                return ValidationResult(
                    is_valid=False,
                    error_code=McpErrorCode.PAYLOAD_TOO_LARGE,
                    error_message=f"Payload size ({byte_len} bytes) exceeds limit ({self.max_payload_bytes} bytes)",
                )
            try:
                decoded = raw_input.decode("utf-8")
            except UnicodeDecodeError as exc:
                return ValidationResult(
                    is_valid=False,
                    error_code=McpErrorCode.PARSE_ERROR,
                    error_message=f"Invalid UTF-8 encoding: {exc}",
                )
        elif isinstance(raw_input, str):
            byte_len = len(raw_input.encode("utf-8"))
            if byte_len > self.max_payload_bytes:
                return ValidationResult(
                    is_valid=False,
                    error_code=McpErrorCode.PAYLOAD_TOO_LARGE,
                    error_message=f"Payload size ({byte_len} bytes) exceeds limit ({self.max_payload_bytes} bytes)",
                )
            decoded = raw_input
        else:
            return ValidationResult(
                is_valid=False,
                error_code=McpErrorCode.INVALID_REQUEST,
                error_message=f"Expected str or bytes input, got {type(raw_input).__name__}",
            )

        try:
            parsed = json.loads(decoded)
        except json.JSONDecodeError as exc:
            return ValidationResult(
                is_valid=False,
                error_code=McpErrorCode.PARSE_ERROR,
                error_message=f"JSON parse error: {exc.msg} at line {exc.lineno} col {exc.colno}",
            )

        return self.validate_parsed(parsed)

    def validate_parsed(self, parsed: Any) -> ValidationResult:
        """Validate an already parsed JSON object or array."""
        if isinstance(parsed, list):
            return self._validate_batch(parsed)
        elif isinstance(parsed, dict):
            return self._validate_single_envelope(parsed)
        else:
            return ValidationResult(
                is_valid=False,
                error_code=McpErrorCode.INVALID_REQUEST,
                error_message="Top-level JSON-RPC entity must be an object or non-empty batch array",
            )

    def _validate_batch(self, batch: List[Any]) -> ValidationResult:
        """Validate a batch request array."""
        if len(batch) == 0:
            return ValidationResult(
                is_valid=False,
                envelope_type=EnvelopeType.BATCH,
                error_code=McpErrorCode.INVALID_REQUEST,
                error_message="Batch request array cannot be empty",
            )

        if len(batch) > self.max_batch_size:
            return ValidationResult(
                is_valid=False,
                envelope_type=EnvelopeType.BATCH,
                error_code=McpErrorCode.INVALID_REQUEST,
                error_message=f"Batch size ({len(batch)}) exceeds maximum limit ({self.max_batch_size})",
            )

        sub_results = [
            self._validate_single_envelope(item) if isinstance(item, dict)
            else ValidationResult(
                is_valid=False,
                error_code=McpErrorCode.INVALID_REQUEST,
                error_message="Batch item must be a JSON object",
            )
            for item in batch
        ]

        all_valid = all(r.is_valid for r in sub_results)
        return ValidationResult(
            is_valid=all_valid,
            envelope_type=EnvelopeType.BATCH,
            details={"batch_size": len(batch), "sub_results": [r.to_dict() for r in sub_results]},
        )

    def _validate_single_envelope(self, env: Dict[str, Any]) -> ValidationResult:
        """Validate a single JSON-RPC 2.0 object envelope."""
        # 1. Version check: "jsonrpc" == "2.0"
        if "jsonrpc" not in env:
            return ValidationResult(
                is_valid=False,
                error_code=McpErrorCode.INVALID_REQUEST,
                error_message="Missing required field 'jsonrpc'",
            )
        if env["jsonrpc"] != "2.0":
            return ValidationResult(
                is_valid=False,
                error_code=McpErrorCode.INVALID_REQUEST,
                error_message=f"Unsupported jsonrpc protocol version: {env['jsonrpc']!r}, expected '2.0'",
            )

        has_id = "id" in env
        has_method = "method" in env
        has_result = "result" in env
        has_error = "error" in env

        # ID type check if present
        request_id = None
        if has_id:
            req_id = env["id"]
            if req_id is not None and not isinstance(req_id, (str, int)):
                # Note: RFC allows fractional floats, but discourages them; reject objects/arrays/booleans
                return ValidationResult(
                    is_valid=False,
                    error_code=McpErrorCode.INVALID_REQUEST,
                    error_message=f"Invalid 'id' type: {type(req_id).__name__}, must be string, integer, or null",
                )
            request_id = req_id

        # Notification Envelope: method present, NO id
        if has_method and not has_id:
            return self._validate_method_invocation(env, EnvelopeType.NOTIFICATION, None)

        # Request Envelope: method present, id present
        if has_method and has_id:
            return self._validate_method_invocation(env, EnvelopeType.REQUEST, request_id)

        # Success Response Envelope: result present, id present, no error, no method
        if has_result and has_id and not has_error and not has_method:
            return ValidationResult(
                is_valid=True,
                envelope_type=EnvelopeType.RESPONSE,
                request_id=request_id,
                details={"result_type": type(env["result"]).__name__},
            )

        # Error Response Envelope: error present, id present, no result, no method
        if has_error and has_id and not has_result and not has_method:
            err = env["error"]
            if not isinstance(err, dict):
                return ValidationResult(
                    is_valid=False,
                    request_id=request_id,
                    envelope_type=EnvelopeType.ERROR,
                    error_code=McpErrorCode.INVALID_REQUEST,
                    error_message="'error' member must be a JSON object",
                )
            if "code" not in err or not isinstance(err["code"], int):
                return ValidationResult(
                    is_valid=False,
                    request_id=request_id,
                    envelope_type=EnvelopeType.ERROR,
                    error_code=McpErrorCode.INVALID_REQUEST,
                    error_message="'error.code' must be an integer",
                )
            if "message" not in err or not isinstance(err["message"], str):
                return ValidationResult(
                    is_valid=False,
                    request_id=request_id,
                    envelope_type=EnvelopeType.ERROR,
                    error_code=McpErrorCode.INVALID_REQUEST,
                    error_message="'error.message' must be a string",
                )
            return ValidationResult(
                is_valid=True,
                envelope_type=EnvelopeType.ERROR,
                request_id=request_id,
                error_code=err["code"],
                error_message=err["message"],
                details=err.get("data", {}) if isinstance(err.get("data"), dict) else {},
            )

        # Malformed combinations (e.g. both result and error, neither method nor result/error, etc.)
        return ValidationResult(
            is_valid=False,
            request_id=request_id,
            error_code=McpErrorCode.INVALID_REQUEST,
            error_message="Invalid envelope: ambiguous combination of method, result, and error members",
        )

    def _validate_method_invocation(
        self, env: Dict[str, Any], env_type: EnvelopeType, request_id: Any
    ) -> ValidationResult:
        """Validate request or notification method name and parameters."""
        method = env["method"]
        if not isinstance(method, str) or not method.strip():
            return ValidationResult(
                is_valid=False,
                envelope_type=env_type,
                request_id=request_id,
                error_code=McpErrorCode.INVALID_REQUEST,
                error_message="'method' must be a non-empty string",
            )

        if not METHOD_NAME_PATTERN.match(method):
            return ValidationResult(
                is_valid=False,
                envelope_type=env_type,
                request_id=request_id,
                method=method,
                error_code=McpErrorCode.INVALID_REQUEST,
                error_message=f"Method name '{method}' does not match allowed syntax",
            )

        if self.require_namespaced_methods and "/" not in method:
            return ValidationResult(
                is_valid=False,
                envelope_type=env_type,
                request_id=request_id,
                method=method,
                error_code=McpErrorCode.INVALID_REQUEST,
                error_message=f"Method '{method}' must be namespaced with a forward slash (e.g. 'tools/call')",
            )

        if self.allowed_methods is not None and method not in self.allowed_methods:
            return ValidationResult(
                is_valid=False,
                envelope_type=env_type,
                request_id=request_id,
                method=method,
                error_code=McpErrorCode.METHOD_NOT_FOUND,
                error_message=f"Method '{method}' is not registered on this server",
            )

        # Validate params if provided
        if "params" in env:
            params = env["params"]
            if not isinstance(params, (dict, list)):
                return ValidationResult(
                    is_valid=False,
                    envelope_type=env_type,
                    request_id=request_id,
                    method=method,
                    error_code=McpErrorCode.INVALID_PARAMS,
                    error_message="'params' member must be a JSON object (by-name) or array (by-position)",
                )

        return ValidationResult(
            is_valid=True,
            envelope_type=env_type,
            request_id=request_id,
            method=method,
        )


def build_error_response(
    request_id: Union[str, int, None],
    code: Union[McpErrorCode, int],
    message: Optional[str] = None,
    data: Any = None,
) -> Dict[str, Any]:
    """Construct a RFC-compliant JSON-RPC 2.0 error response dictionary."""
    resolved_message = message or STANDARD_ERROR_MESSAGES.get(int(code), "Unknown error")
    error_obj: Dict[str, Any] = {
        "code": int(code),
        "message": resolved_message,
    }
    if data is not None:
        error_obj["data"] = data

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": error_obj,
    }


def build_success_response(
    request_id: Union[str, int, None],
    result: Any,
) -> Dict[str, Any]:
    """Construct a RFC-compliant JSON-RPC 2.0 success response dictionary."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    }
