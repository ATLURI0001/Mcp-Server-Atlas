"""
MCP Tool Call Argument Sanitizer & Injection Guard.

Provides defensive boundary validation for LLM-generated tool arguments, including
path traversal containment, shell command metacharacter filtering, and SSRF protection.
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse


FORBIDDEN_SHELL_CHARS_REGEX = re.compile(r"[;&|`$><!\n\r\t]")

BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
    "instance-data",
}


class ToolSanitizationError(Exception):
    """Raised when an argument fails security sanitization."""


class ToolArgumentSanitizer:
    """Defensive sanitizer protecting MCP tools against injection and SSRF."""

    def __init__(
        self,
        allowed_base_dir: str | Path | None = None,
        allow_private_ips: bool = False,
        max_string_len: int = 65536,
        max_recursion_depth: int = 6,
    ) -> None:
        self.allowed_base_dir = Path(allowed_base_dir).resolve() if allowed_base_dir else None
        self.allow_private_ips = allow_private_ips
        self.max_string_len = max_string_len
        self.max_recursion_depth = max_recursion_depth

    def sanitize_file_path(self, path_str: str) -> Path:
        """Contain and validate file path, preventing null byte and traversal attacks."""
        if not path_str or not isinstance(path_str, str):
            raise ToolSanitizationError("File path must be a non-empty string.")

        if "\x00" in path_str:
            raise ToolSanitizationError("Null byte detected in file path.")

        # Traversal pattern check
        cleaned = path_str.strip()
        if ".." in cleaned.replace("\\", "/").split("/"):
            # Check if traversing above base
            resolved = Path(cleaned).resolve()
            if self.allowed_base_dir and not resolved.is_relative_to(self.allowed_base_dir):
                raise ToolSanitizationError(f"Path traversal detected: '{path_str}' escapes allowed base.")

        resolved = Path(cleaned).resolve()
        if self.allowed_base_dir and not resolved.is_relative_to(self.allowed_base_dir):
            raise ToolSanitizationError(f"Path '{path_str}' is outside allowed directory '{self.allowed_base_dir}'.")

        return resolved

    def sanitize_command_arg(self, arg: str) -> str:
        """Inspect and sanitize CLI arguments against shell injection metacharacters."""
        if not isinstance(arg, str):
            raise ToolSanitizationError("Command argument must be a string.")

        if len(arg) > self.max_string_len:
            raise ToolSanitizationError(f"Argument exceeds maximum length ({len(arg)} > {self.max_string_len}).")

        if "\x00" in arg:
            raise ToolSanitizationError("Null byte detected in command argument.")

        if FORBIDDEN_SHELL_CHARS_REGEX.search(arg):
            raise ToolSanitizationError(f"Dangerous shell metacharacters detected in argument: '{arg}'")

        return arg.strip()

    def sanitize_url(self, url: str) -> str:
        """Validate URL against SSRF, blocking loopback, link-local, and cloud metadata endpoints."""
        if not url or not isinstance(url, str):
            raise ToolSanitizationError("URL must be a non-empty string.")

        if "\x00" in url:
            raise ToolSanitizationError("Null byte detected in URL.")

        try:
            parsed = urlparse(url.strip())
        except Exception as e:
            raise ToolSanitizationError(f"Malformed URL: {e}") from e

        if parsed.scheme not in ("http", "https"):
            raise ToolSanitizationError(f"Unsupported URL scheme '{parsed.scheme}'. Only http and https allowed.")

        hostname = (parsed.hostname or "").lower().strip()
        if not hostname:
            raise ToolSanitizationError("URL is missing a valid hostname.")

        if hostname in BLOCKED_HOSTNAMES:
            raise ToolSanitizationError(f"SSRF attempt: access to '{hostname}' is blocked.")

        # Check IP addresses (loopback, private, link-local metadata)
        try:
            ip = ipaddress.ip_address(hostname)
            if not self.allow_private_ips:
                if ip.is_loopback:
                    raise ToolSanitizationError(f"SSRF attempt: loopback address '{ip}' blocked.")
                if ip.is_private:
                    raise ToolSanitizationError(f"SSRF attempt: private network address '{ip}' blocked.")
                if ip.is_link_local:
                    raise ToolSanitizationError(f"SSRF attempt: link-local address '{ip}' blocked.")
                if str(ip) == "169.254.169.254":
                    raise ToolSanitizationError("SSRF attempt: cloud instance metadata IP blocked.")
        except ValueError:
            # Hostname is a domain name, not raw IP literal
            pass

        return url.strip()

    def sanitize_payload(self, payload: Any, depth: int = 0) -> Any:
        """Recursively inspect argument payload ensuring depth and size boundaries."""
        if depth > self.max_recursion_depth:
            raise ToolSanitizationError(f"Payload exceeded maximum recursion depth of {self.max_recursion_depth}.")

        if isinstance(payload, str):
            if len(payload) > self.max_string_len:
                raise ToolSanitizationError(f"String argument exceeds size budget ({len(payload)} chars).")
            if "\x00" in payload:
                raise ToolSanitizationError("Null byte detected in string argument.")
            return payload

        if isinstance(payload, dict):
            sanitized_dict: dict[str, Any] = {}
            for k, v in payload.items():
                if not isinstance(k, str) or "\x00" in k:
                    raise ToolSanitizationError("Invalid dictionary key in tool payload.")
                sanitized_dict[k] = self.sanitize_payload(v, depth + 1)
            return sanitized_dict

        if isinstance(payload, (list, tuple)):
            return [self.sanitize_payload(item, depth + 1) for item in payload]

        return payload
