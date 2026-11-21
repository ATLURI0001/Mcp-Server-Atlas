"""Community MCP Server submission metadata ingress contract and security sanitizer."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any, List, Mapping
from urllib.parse import urlparse, urlunparse


class SubmissionValidationError(ValueError):
    """Raised when an MCP server submission violates catalog ingress schema or security constraints."""


SERVER_NAME_REGEX = re.compile(r"^[a-z0-9][a-z0-9-_]{1,63}$")
VALID_TRANSPORTS = frozenset({"stdio", "sse", "stream"})
VALID_CAPABILITIES = frozenset({"tools", "resources", "prompts", "logging"})
ALLOWED_REPO_HOSTS = frozenset({"github.com", "gitlab.com", "codeberg.org", "bitbucket.org"})
COMMON_SPDX_LICENSES = frozenset({
    "mit", "apache-2.0", "gpl-3.0", "gpl-2.0", "lgpl-3.0", "agpl-3.0",
    "bsd-2-clause", "bsd-3-clause", "mpl-2.0", "isc", "unlicense", "cc0-1.0",
})


def validate_server_name(name: Any) -> str:
    """Validate server slug: 2-64 chars, lowercase alphanumeric with hyphens/underscores."""
    if not isinstance(name, str):
        raise SubmissionValidationError("Server name must be a string")
    clean = name.strip().lower()
    if not clean:
        raise SubmissionValidationError("Server name cannot be empty")
    if clean.endswith("-") or clean.endswith("_"):
        raise SubmissionValidationError("Server name cannot end with a hyphen or underscore")
    if not SERVER_NAME_REGEX.match(clean):
        raise SubmissionValidationError(
            f"Invalid server name '{clean}'. Must match ^[a-z0-9][a-z0-9-_]{{1,63}}$"
        )
    return clean


def validate_repo_url(url: Any) -> str:
    """Validate repository URL: HTTPS only, approved forge domain, no credentials or tracking params."""
    if not isinstance(url, str):
        raise SubmissionValidationError("Repository URL must be a string")
    clean = url.strip()
    if not clean:
        raise SubmissionValidationError("Repository URL cannot be empty")

    parsed = urlparse(clean)
    if parsed.scheme.lower() != "https":
        raise SubmissionValidationError(f"Repository URL must use https scheme, got '{parsed.scheme}'")

    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_REPO_HOSTS:
        raise SubmissionValidationError(
            f"Host '{host}' is not an authorized repository forge. Expected one of {sorted(ALLOWED_REPO_HOSTS)}"
        )

    if parsed.username or parsed.password:
        raise SubmissionValidationError("Repository URL must not contain embedded user credentials")

    path_segments = [p for p in parsed.path.split("/") if p]
    if len(path_segments) < 2:
        raise SubmissionValidationError(
            f"Repository URL path '{parsed.path}' must contain owner and repository name (e.g. /owner/repo)"
        )

    # Reconstruct sanitized canonical URL without query parameters or fragments
    clean_path = f"/{path_segments[0]}/{path_segments[1].removesuffix('.git')}"
    return urlunparse(("https", host, clean_path, "", "", ""))


def validate_transport(transport: Any) -> str:
    """Validate MCP transport protocol."""
    if not isinstance(transport, str):
        raise SubmissionValidationError("Transport must be a string")
    clean = transport.strip().lower()
    if clean not in VALID_TRANSPORTS:
        raise SubmissionValidationError(
            f"Invalid transport '{clean}'. Must be one of {sorted(VALID_TRANSPORTS)}"
        )
    return clean


def validate_capabilities(caps: Any) -> List[str]:
    """Validate declared server capabilities."""
    if not isinstance(caps, (list, tuple, set)):
        raise SubmissionValidationError("Capabilities must be a list of strings")
    if not caps:
        raise SubmissionValidationError("Server must declare at least one capability")

    cleaned = set()
    for c in caps:
        if not isinstance(c, str):
            raise SubmissionValidationError(f"Capability '{c}' must be a string")
        c_clean = c.strip().lower()
        if c_clean not in VALID_CAPABILITIES:
            raise SubmissionValidationError(
                f"Unknown capability '{c_clean}'. Must be one of {sorted(VALID_CAPABILITIES)}"
            )
        cleaned.add(c_clean)

    return sorted(cleaned)


def sanitize_description(desc: Any) -> str:
    """Validate and sanitize server description, neutralizing HTML tags."""
    if not isinstance(desc, str):
        raise SubmissionValidationError("Description must be a string")
    clean = desc.strip()
    if len(clean) < 10:
        raise SubmissionValidationError("Description must be at least 10 characters")
    if len(clean) > 500:
        raise SubmissionValidationError("Description exceeds maximum length of 500 characters")

    # Guard against script injection or raw iframe tags
    if re.search(r"<\s*(script|iframe|object|embed|style)\b", clean, re.IGNORECASE):
        raise SubmissionValidationError("Description contains forbidden executable HTML tags")

    # Escape any HTML entities for safe rendering
    escaped = html.escape(clean, quote=True)
    return escaped


def validate_license(license_str: Any) -> str:
    """Validate open-source license string."""
    if not isinstance(license_str, str):
        raise SubmissionValidationError("License must be a string")
    clean = license_str.strip()
    if not clean:
        raise SubmissionValidationError("License identifier cannot be empty")

    if clean.lower() not in COMMON_SPDX_LICENSES and not re.match(r"^[A-Za-z0-9\.\-]+$", clean):
        raise SubmissionValidationError(f"Invalid license identifier '{clean}'")

    return clean


@dataclass(frozen=True)
class ServerSubmission:
    """Validated, sanitized server submission record."""

    name: str
    repo_url: str
    transport: str
    capabilities: List[str]
    description: str
    license: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "repo_url": self.repo_url,
            "transport": self.transport,
            "capabilities": list(self.capabilities),
            "description": self.description,
            "license": self.license,
        }


def validate_submission_payload(payload: Mapping[str, Any]) -> ServerSubmission:
    """Validate an entire inbound server submission dictionary."""
    if not isinstance(payload, Mapping):
        raise SubmissionValidationError("Submission payload must be a mapping/dictionary")

    required_fields = ("name", "repo_url", "transport", "capabilities", "description", "license")
    missing = [f for f in required_fields if f not in payload]
    if missing:
        raise SubmissionValidationError(f"Missing required submission fields: {missing}")

    name = validate_server_name(payload["name"])
    repo_url = validate_repo_url(payload["repo_url"])
    transport = validate_transport(payload["transport"])
    capabilities = validate_capabilities(payload["capabilities"])
    description = sanitize_description(payload["description"])
    license_val = validate_license(payload["license"])

    return ServerSubmission(
        name=name,
        repo_url=repo_url,
        transport=transport,
        capabilities=capabilities,
        description=description,
        license=license_val,
    )
