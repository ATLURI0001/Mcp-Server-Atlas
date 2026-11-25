"""
MCP Ingress Payload Buffer & Deep Nesting Sentinel.

Incident Postmortem Root Cause Fix: INC-2026-MCP-9102
Mitigates recursive JSON-RPC nested object attacks, mega-byte unchunked string injections,
and unbounded memory buffer allocations across MCP server ingress transports.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class ViolationType(str, Enum):
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    EXCESSIVE_NESTING_DEPTH = "EXCESSIVE_NESTING_DEPTH"
    EXCESSIVE_KEY_COUNT = "EXCESSIVE_KEY_COUNT"
    EXCESSIVE_ARRAY_LENGTH = "EXCESSIVE_ARRAY_LENGTH"
    STRING_LENGTH_EXCEEDED = "STRING_LENGTH_EXCEEDED"
    INVALID_JSON_ENCODING = "INVALID_JSON_ENCODING"


class PayloadSentinelError(Exception):
    """Raised when an incoming MCP JSON-RPC payload violates buffer limits."""
    def __init__(self, violation: ViolationType, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(f"[{violation.value}] {message}")
        self.violation = violation
        self.message = message
        self.context = context or {}


@dataclass
class SentinelInspectionResult:
    is_safe: bool
    estimated_memory_bytes: int
    max_observed_depth: int
    total_nodes: int
    violations: List[Tuple[ViolationType, str]] = field(default_factory=list)


class PayloadBufferSentinel:
    """Ingress defensive sentinel validating payload memory and recursion bounds."""

    def __init__(
        self,
        max_payload_bytes: int = 4 * 1024 * 1024,  # 4 MB
        max_depth: int = 16,
        max_keys_per_object: int = 500,
        max_array_length: int = 2000,
        max_string_length: int = 256 * 1024,  # 256 KB
    ) -> None:
        self.max_payload_bytes = max_payload_bytes
        self.max_depth = max_depth
        self.max_keys_per_object = max_keys_per_object
        self.max_array_length = max_array_length
        self.max_string_length = max_string_length

    def inspect_raw_bytes(self, raw_bytes: bytes) -> None:
        """Enforces fast byte-length check before JSON parsing to avoid parser memory explosions."""
        if len(raw_bytes) > self.max_payload_bytes:
            raise PayloadSentinelError(
                ViolationType.PAYLOAD_TOO_LARGE,
                f"Raw payload size {len(raw_bytes)} bytes exceeds limit of {self.max_payload_bytes} bytes",
                {"size_bytes": len(raw_bytes), "limit_bytes": self.max_payload_bytes},
            )

    def validate_payload(self, data: Any) -> SentinelInspectionResult:
        """
        Deeply inspects parsed JSON object structure, enforcing strict recursion depth,
        key counts, string lengths, and calculating estimated memory allocations.
        """
        violations: List[Tuple[ViolationType, str]] = []
        max_depth_seen = 0
        total_nodes = 0
        total_estimated_bytes = 0

        def _traverse(node: Any, current_depth: int) -> None:
            nonlocal max_depth_seen, total_nodes, total_estimated_bytes

            total_nodes += 1
            max_depth_seen = max(max_depth_seen, current_depth)

            if current_depth > self.max_depth:
                violations.append((
                    ViolationType.EXCESSIVE_NESTING_DEPTH,
                    f"Nesting depth {current_depth} exceeds max allowed depth of {self.max_depth}",
                ))
                return

            if isinstance(node, dict):
                total_estimated_bytes += 64 + (len(node) * 16)
                if len(node) > self.max_keys_per_object:
                    violations.append((
                        ViolationType.EXCESSIVE_KEY_COUNT,
                        f"Object key count {len(node)} exceeds maximum of {self.max_keys_per_object}",
                    ))
                for key, val in node.items():
                    if not isinstance(key, str):
                        key_str = str(key)
                    else:
                        key_str = key
                    total_estimated_bytes += len(key_str.encode("utf-8", errors="ignore"))
                    _traverse(val, current_depth + 1)

            elif isinstance(node, (list, tuple)):
                total_estimated_bytes += 64 + (len(node) * 8)
                if len(node) > self.max_array_length:
                    violations.append((
                        ViolationType.EXCESSIVE_ARRAY_LENGTH,
                        f"Array length {len(node)} exceeds maximum of {self.max_array_length}",
                    ))
                for item in node:
                    _traverse(item, current_depth + 1)

            elif isinstance(node, str):
                str_bytes = len(node.encode("utf-8", errors="ignore"))
                total_estimated_bytes += 48 + str_bytes
                if str_bytes > self.max_string_length:
                    violations.append((
                        ViolationType.STRING_LENGTH_EXCEEDED,
                        f"String length {str_bytes} bytes exceeds maximum of {self.max_string_length}",
                    ))

            elif isinstance(node, (int, float)):
                total_estimated_bytes += 24
            elif isinstance(node, bool) or node is None:
                total_estimated_bytes += 16

        _traverse(data, current_depth=1)

        if violations:
            first_v, msg = violations[0]
            raise PayloadSentinelError(first_v, msg, {"violations_count": len(violations)})

        return SentinelInspectionResult(
            is_safe=True,
            estimated_memory_bytes=total_estimated_bytes,
            max_observed_depth=max_depth_seen,
            total_nodes=total_nodes,
            violations=violations,
        )

    def sanitize_and_parse(self, raw_input: bytes | str) -> Tuple[Any, SentinelInspectionResult]:
        """Validates raw input stream, parses JSON, and performs structure verification."""
        if isinstance(raw_input, str):
            raw_bytes = raw_input.encode("utf-8")
        else:
            raw_bytes = raw_input

        self.inspect_raw_bytes(raw_bytes)

        try:
            parsed = json.loads(raw_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise PayloadSentinelError(
                ViolationType.INVALID_JSON_ENCODING,
                f"Malformed JSON payload: {e}",
            )

        inspection = self.validate_payload(parsed)
        return parsed, inspection
