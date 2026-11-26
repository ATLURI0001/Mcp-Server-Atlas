"""
MCP Resource URI & Subscription Boundary Contract for Mcp-Server-Atlas.

Enforces strict RFC 3986 URI parsing, MIME type schema validation,
path traversal isolation, and subscription capacity boundaries across MCP resources.
"""

from __future__ import annotations

import base64
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


class ResourceContractViolationError(ValueError):
    """Raised when an MCP resource specification or request violates contract bounds."""
    pass


class InvalidResourceURIError(ResourceContractViolationError):
    """Raised when a resource URI is malformed, uses invalid scheme, or contains traversal."""
    pass


class SubscriptionLimitExceededError(ResourceContractViolationError):
    """Raised when a client session breaches the maximum resource subscription boundary."""
    pass


class InvalidCursorError(ResourceContractViolationError):
    """Raised when a pagination cursor token is malformed."""
    pass


MIME_TYPE_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.]+/[a-zA-Z0-9_\-\.]+$")
ALLOWED_SCHEMES = {"file", "resource", "memo", "postgres", "mysql", "custom", "atlas"}


@dataclass(frozen=True)
class MCPResourceMetadata:
    """Immutable MCP resource descriptor conforming to protocol schema."""
    uri: str
    name: str
    mime_type: str
    description: Optional[str] = None
    size_bytes: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "uri": self.uri,
            "name": self.name,
            "mimeType": self.mime_type,
        }
        if self.description is not None:
            data["description"] = self.description
        if self.size_bytes is not None:
            data["sizeBytes"] = self.size_bytes
        return data


class ResourceURIContract:
    """Validates and enforces boundary invariants on MCP resources and subscriptions."""

    def __init__(
        self,
        max_uri_length: int = 512,
        max_subscriptions_per_session: int = 100,
        max_page_size: int = 250,
        allowed_schemes: Optional[Set[str]] = None,
    ):
        if max_uri_length < 16:
            raise ValueError("max_uri_length must be at least 16")
        if max_subscriptions_per_session < 1:
            raise ValueError("max_subscriptions_per_session must be at least 1")
        if max_page_size < 1:
            raise ValueError("max_page_size must be at least 1")

        self.max_uri_length = max_uri_length
        self.max_subscriptions_per_session = max_subscriptions_per_session
        self.max_page_size = max_page_size
        self.allowed_schemes = allowed_schemes or ALLOWED_SCHEMES
        self._subscriptions: Dict[str, Set[str]] = {}

    def validate_uri(self, uri: str) -> str:
        """Validate that a resource URI is safe, well-formed, and within schema bounds."""
        if not uri or not isinstance(uri, str):
            raise InvalidResourceURIError(f"Resource URI must be a non-empty string, got: {uri}")

        trimmed = uri.strip()
        if len(trimmed) > self.max_uri_length:
            raise InvalidResourceURIError(
                f"Resource URI length ({len(trimmed)}) exceeds max allowed boundary of {self.max_uri_length}"
            )

        # Check for control characters
        if any(ord(c) < 32 or ord(c) == 127 for c in trimmed):
            raise InvalidResourceURIError("Resource URI contains forbidden ASCII control characters")

        # Parse scheme
        try:
            parsed = urllib.parse.urlparse(trimmed)
        except Exception as exc:
            raise InvalidResourceURIError(f"Malformed URI: {exc}") from exc

        if not parsed.scheme:
            raise InvalidResourceURIError(f"Resource URI must declare an explicit scheme: '{trimmed}'")

        if parsed.scheme.lower() not in self.allowed_schemes:
            raise InvalidResourceURIError(
                f"URI scheme '{parsed.scheme}' is not permitted. Allowed: {sorted(self.allowed_schemes)}"
            )

        # Check for path traversal attacks in path component
        path = parsed.path
        if ".." in path or "/./" in path or path.endswith("/."):
            raise InvalidResourceURIError(f"Resource URI contains forbidden path traversal sequences: '{trimmed}'")

        return trimmed

    def validate_resource(self, raw: Dict[str, Any]) -> MCPResourceMetadata:
        """Validate complete resource declaration dictionary."""
        if not isinstance(raw, dict):
            raise ResourceContractViolationError("Resource declaration must be a dictionary")

        uri = self.validate_uri(raw.get("uri", ""))

        name = raw.get("name")
        if not name or not isinstance(name, str) or not name.strip():
            raise ResourceContractViolationError(f"Resource '{uri}' must define a non-empty name")
        name = name.strip()
        if len(name) > 64:
            raise ResourceContractViolationError(f"Resource name exceeds 64 characters: '{name}'")

        mime_type = raw.get("mimeType")
        if not mime_type or not isinstance(mime_type, str):
            raise ResourceContractViolationError(f"Resource '{uri}' must declare a valid mimeType")
        mime_type = mime_type.strip().lower()
        if not MIME_TYPE_REGEX.match(mime_type):
            raise ResourceContractViolationError(f"Invalid MIME type format '{mime_type}' for resource '{uri}'")

        description = raw.get("description")
        if description is not None:
            if not isinstance(description, str) or len(description) > 512:
                raise ResourceContractViolationError("Resource description must be string <= 512 chars")
            description = description.strip()

        size_bytes = raw.get("sizeBytes")
        if size_bytes is not None:
            if not isinstance(size_bytes, int) or size_bytes < 0:
                raise ResourceContractViolationError("sizeBytes must be a non-negative integer")

        return MCPResourceMetadata(
            uri=uri,
            name=name,
            mime_type=mime_type,
            description=description,
            size_bytes=size_bytes,
        )

    def subscribe_resource(self, session_id: str, uri: str) -> None:
        """Subscribe a client session to resource update notifications with capacity guard."""
        valid_uri = self.validate_uri(uri)
        if not session_id or not isinstance(session_id, str):
            raise ValueError("session_id must be a non-empty string")

        if session_id not in self._subscriptions:
            self._subscriptions[session_id] = set()

        subs = self._subscriptions[session_id]
        if valid_uri not in subs and len(subs) >= self.max_subscriptions_per_session:
            raise SubscriptionLimitExceededError(
                f"Session '{session_id}' exceeded max subscription boundary of {self.max_subscriptions_per_session}"
            )

        subs.add(valid_uri)

    def unsubscribe_resource(self, session_id: str, uri: str) -> bool:
        """Unsubscribe a client session from resource updates."""
        valid_uri = self.validate_uri(uri)
        if session_id in self._subscriptions:
            if valid_uri in self._subscriptions[session_id]:
                self._subscriptions[session_id].remove(valid_uri)
                return True
        return False

    def get_subscriptions(self, session_id: str) -> List[str]:
        """Return ordered list of active resource subscriptions for a session."""
        return sorted(self._subscriptions.get(session_id, set()))

    def encode_cursor(self, offset: int) -> str:
        """Encode an opaque base64 pagination cursor."""
        if offset < 0:
            raise ValueError("Offset cannot be negative")
        raw = f"cursor:{offset}"
        return base64.b64encode(raw.encode("utf-8")).decode("utf-8")

    def decode_cursor(self, cursor: str) -> int:
        """Decode and validate an opaque pagination cursor."""
        if not cursor or not isinstance(cursor, str):
            raise InvalidCursorError("Cursor must be a non-empty string")
        try:
            decoded = base64.b64decode(cursor.encode("utf-8")).decode("utf-8")
            if not decoded.startswith("cursor:"):
                raise InvalidCursorError("Malformed cursor prefix")
            offset = int(decoded.split(":", 1)[1])
            if offset < 0:
                raise InvalidCursorError("Negative cursor offset")
            return offset
        except Exception as exc:
            raise InvalidCursorError(f"Invalid pagination cursor: {exc}") from exc
