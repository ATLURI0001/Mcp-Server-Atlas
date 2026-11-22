"""JSON-RPC Transport Frame Validator and Content-Length Framing Hardener.

Implements strict, streaming RFC-compliant framing for Model Context Protocol (MCP)
and Language Server Protocol (LSP) transport layers over stdio and streaming sockets.
Defends against Content-Length header smuggling, buffer exhaustion, and UTF-8 encoding truncation.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

HEADER_DELIMITER = b"\r\n\r\n"
LINE_DELIMITER = b"\r\n"
CONTENT_LENGTH_HEADER = "Content-Length"
CONTENT_TYPE_HEADER = "Content-Type"
DEFAULT_CONTENT_TYPE = "application/vscode-jsonrpc; charset=utf-8"

CRLF_INJECTION_PATTERN = re.compile(r"[\r\n]")


class FramingError(Exception):
    """Raised when transport frame structure or byte length is violated."""


@dataclass
class TransportFrame:
    """Represents a validated, decoded JSON-RPC transport frame."""

    headers: Dict[str, str]
    content_length: int
    body_bytes: bytes
    payload: Dict[str, Any]


class TransportFramingCodec:
    """Encodes and decodes streaming JSON-RPC frames with defensive bounds checking."""

    def __init__(self, max_frame_bytes: int = 10 * 1024 * 1024) -> None:
        self.max_frame_bytes = max(1024, int(max_frame_bytes))
        self._buffer = bytearray()

    @staticmethod
    def encode_frame(payload: Dict[str, Any], include_content_type: bool = True) -> bytes:
        """Serializes and frames a JSON-RPC payload with exact Content-Length headers.

        Args:
            payload: JSON serializable dictionary.
            include_content_type: If True, adds Content-Type header.

        Returns:
            Encoded bytes formatted as:
            Content-Length: <N>\r\n[Content-Type: ...\r\n]\r\n<JSON>
        """
        # Ensure UTF-8 byte serialization without spaces around separators for consistency
        json_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        byte_length = len(json_bytes)

        headers = [f"{CONTENT_LENGTH_HEADER}: {byte_length}"]
        if include_content_type:
            headers.append(f"{CONTENT_TYPE_HEADER}: {DEFAULT_CONTENT_TYPE}")

        header_bytes = "\r\n".join(headers).encode("ascii") + b"\r\n\r\n"
        return header_bytes + json_bytes

    def feed_bytes(self, chunk: bytes) -> List[TransportFrame]:
        """Feeds raw byte chunks into the streaming decoder and extracts complete frames.

        Args:
            chunk: Arbitrary length byte sequence from stream/socket.

        Returns:
            List of successfully decoded and validated TransportFrames.
        """
        if not chunk:
            return []

        self._buffer.extend(chunk)
        frames: List[TransportFrame] = []

        while True:
            # Check for header end delimiter
            delimiter_idx = self._buffer.find(HEADER_DELIMITER)
            if delimiter_idx == -1:
                # Still waiting for full headers
                if len(self._buffer) > 65536:
                    self._buffer.clear()
                    raise FramingError("Header section exceeds 64KB boundary without delimiter")
                break

            header_raw = bytes(self._buffer[:delimiter_idx])
            headers = self._parse_headers(header_raw)

            if CONTENT_LENGTH_HEADER not in headers:
                self._buffer.clear()
                raise FramingError(f"Missing mandatory '{CONTENT_LENGTH_HEADER}' header")

            try:
                content_length = int(headers[CONTENT_LENGTH_HEADER])
                if content_length < 0:
                    raise ValueError()
            except ValueError:
                self._buffer.clear()
                raise FramingError(f"Invalid Content-Length numeric value: '{headers[CONTENT_LENGTH_HEADER]}'")

            if content_length > self.max_frame_bytes:
                self._buffer.clear()
                raise FramingError(
                    f"Content-Length ({content_length}) exceeds maximum boundary ({self.max_frame_bytes})"
                )

            body_start_idx = delimiter_idx + len(HEADER_DELIMITER)
            body_end_idx = body_start_idx + content_length

            # Check if entire body has arrived
            if len(self._buffer) < body_end_idx:
                # Buffer has headers, but waiting for remaining body bytes
                break

            body_bytes = bytes(self._buffer[body_start_idx:body_end_idx])

            # Advance buffer past this completed frame
            del self._buffer[:body_end_idx]

            # Parse JSON payload
            try:
                payload = json.loads(body_bytes.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("JSON-RPC payload must be a JSON object")
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as err:
                raise FramingError(f"Malformed JSON-RPC payload in frame body: {err}")

            frames.append(
                TransportFrame(
                    headers=headers,
                    content_length=content_length,
                    body_bytes=body_bytes,
                    payload=payload,
                )
            )

        return frames

    @staticmethod
    def _parse_headers(raw_bytes: bytes) -> Dict[str, str]:
        """Parses and sanitizes header lines, defending against CRLF injection."""
        try:
            header_text = raw_bytes.decode("ascii")
        except UnicodeDecodeError:
            raise FramingError("Transport headers contain non-ASCII characters")

        lines = header_text.split("\r\n")
        parsed: Dict[str, str] = {}

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            if ":" not in line_str:
                raise FramingError(f"Invalid header line without colon: '{line_str}'")

            key, val = line_str.split(":", 1)
            norm_key = key.strip()
            norm_val = val.strip()

            if CRLF_INJECTION_PATTERN.search(norm_key) or CRLF_INJECTION_PATTERN.search(norm_val):
                raise FramingError("CRLF injection detected in transport header")

            # Canonicalize key casing for Content-Length and Content-Type
            for canonical in [CONTENT_LENGTH_HEADER, CONTENT_TYPE_HEADER]:
                if norm_key.lower() == canonical.lower():
                    norm_key = canonical
                    break

            parsed[norm_key] = norm_val

        return parsed

    def reset(self) -> None:
        """Flushes the internal buffer."""
        self._buffer.clear()
