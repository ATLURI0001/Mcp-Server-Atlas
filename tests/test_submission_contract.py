"""Unit tests for ServerSubmission contract and metadata sanitization routines."""

from __future__ import annotations

import pytest
from scripts.submission_contract import (
    SubmissionValidationError,
    sanitize_description,
    validate_capabilities,
    validate_license,
    validate_repo_url,
    validate_server_name,
    validate_submission_payload,
    validate_transport,
)


def test_validate_server_name() -> None:
    assert validate_server_name("postgres-mcp") == "postgres-mcp"
    assert validate_server_name("Filesystem_Server") == "filesystem_server"
    assert validate_server_name("a1") == "a1"

    with pytest.raises(SubmissionValidationError, match="cannot end with a hyphen"):
        validate_server_name("invalid-name-")

    with pytest.raises(SubmissionValidationError, match="Invalid server name"):
        validate_server_name("-invalid")

    with pytest.raises(SubmissionValidationError, match="Invalid server name"):
        validate_server_name("has spaces")


def test_validate_repo_url() -> None:
    assert (
        validate_repo_url("https://github.com/modelcontextprotocol/servers.git?ref=main")
        == "https://github.com/modelcontextprotocol/servers"
    )
    assert (
        validate_repo_url("https://gitlab.com/org/mcp-tool")
        == "https://gitlab.com/org/mcp-tool"
    )

    # Reject HTTP
    with pytest.raises(SubmissionValidationError, match="must use https"):
        validate_repo_url("http://github.com/org/repo")

    # Reject unauthorized domain
    with pytest.raises(SubmissionValidationError, match="not an authorized repository forge"):
        validate_repo_url("https://malicious-site.com/org/repo")

    # Reject embedded userinfo
    with pytest.raises(SubmissionValidationError, match="embedded user credentials"):
        validate_repo_url("https://token:secret@github.com/org/repo")

    # Reject insufficient path segments
    with pytest.raises(SubmissionValidationError, match="must contain owner and repository name"):
        validate_repo_url("https://github.com/org")


def test_validate_transport() -> None:
    assert validate_transport("STDIO") == "stdio"
    assert validate_transport("sse") == "sse"
    assert validate_transport("stream") == "stream"

    with pytest.raises(SubmissionValidationError, match="Invalid transport"):
        validate_transport("websocket")


def test_validate_capabilities() -> None:
    assert validate_capabilities(["tools", "resources"]) == ["resources", "tools"]
    assert validate_capabilities(["Tools", "tools", "PROMPTS"]) == ["prompts", "tools"]

    with pytest.raises(SubmissionValidationError, match="at least one capability"):
        validate_capabilities([])

    with pytest.raises(SubmissionValidationError, match="Unknown capability"):
        validate_capabilities(["tools", "telepathy"])


def test_sanitize_description() -> None:
    valid_desc = "High performance PostgreSQL database integration tool for MCP."
    assert sanitize_description(valid_desc) == valid_desc

    # Too short
    with pytest.raises(SubmissionValidationError, match="at least 10 characters"):
        sanitize_description("Short")

    # Script injection rejection
    with pytest.raises(SubmissionValidationError, match="forbidden executable HTML tags"):
        sanitize_description("A safe tool <script>alert(1)</script> for data.")

    # HTML entity escaping
    escaped = sanitize_description("Tool supporting a > b & c < d queries.")
    assert "&gt;" in escaped
    assert "&lt;" in escaped


def test_validate_license() -> None:
    assert validate_license("MIT") == "MIT"
    assert validate_license("Apache-2.0") == "Apache-2.0"
    assert validate_license("BSD-3-Clause") == "BSD-3-Clause"

    with pytest.raises(SubmissionValidationError, match="cannot be empty"):
        validate_license("")


def test_validate_submission_payload_end_to_end() -> None:
    raw_payload = {
        "name": "sqlite-atlas",
        "repo_url": "https://github.com/modelcontextprotocol/servers/tree/main/src/sqlite",
        "transport": "stdio",
        "capabilities": ["tools", "resources"],
        "description": "Standard SQLite database inspection and querying MCP server.",
        "license": "MIT",
    }

    sub = validate_submission_payload(raw_payload)
    assert sub.name == "sqlite-atlas"
    assert sub.repo_url == "https://github.com/modelcontextprotocol/servers"
    assert sub.transport == "stdio"
    assert sub.capabilities == ["resources", "tools"]
    assert sub.license == "MIT"

    exported = sub.to_dict()
    assert exported["name"] == "sqlite-atlas"

    # Missing field error
    incomplete = dict(raw_payload)
    del incomplete["license"]
    with pytest.raises(SubmissionValidationError, match="Missing required"):
        validate_submission_payload(incomplete)
