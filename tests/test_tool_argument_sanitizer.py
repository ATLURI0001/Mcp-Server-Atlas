"""Tests for the MCP Tool Call Argument Sanitizer & Injection Guard."""

from pathlib import Path
import pytest
from scripts.tool_argument_sanitizer import (
    ToolArgumentSanitizer,
    ToolSanitizationError,
)


def test_sanitize_file_path_containment(tmp_path: Path) -> None:
    sanitizer = ToolArgumentSanitizer(allowed_base_dir=tmp_path)

    # Valid subfile
    valid_file = tmp_path / "data" / "report.json"
    resolved = sanitizer.sanitize_file_path(str(valid_file))
    assert resolved == valid_file.resolve()

    # Traversal escape outside base
    with pytest.raises(ToolSanitizationError, match="Path traversal detected|outside allowed directory"):
        sanitizer.sanitize_file_path(str(tmp_path / ".." / "secret.txt"))

    # Null byte detection
    with pytest.raises(ToolSanitizationError, match="Null byte detected"):
        sanitizer.sanitize_file_path(f"{tmp_path}/data\x00.json")


def test_sanitize_command_arg_injection() -> None:
    sanitizer = ToolArgumentSanitizer()

    # Valid arguments
    assert sanitizer.sanitize_command_arg("--verbose") == "--verbose"
    assert sanitizer.sanitize_command_arg("build-target-123") == "build-target-123"

    # Shell injection attempts
    dangerous = [
        "file.txt; rm -rf /",
        "test && whoami",
        "data | grep secret",
        "`cat /etc/passwd`",
        "$(uname -a)",
        "output.txt > /dev/null",
        "arg\nmalicious_cmd",
    ]

    for attack in dangerous:
        with pytest.raises(ToolSanitizationError, match="Dangerous shell metacharacters"):
            sanitizer.sanitize_command_arg(attack)

    # Null byte
    with pytest.raises(ToolSanitizationError, match="Null byte detected"):
        sanitizer.sanitize_command_arg("arg\x00extra")


def test_sanitize_url_ssrf_mitigation() -> None:
    sanitizer = ToolArgumentSanitizer()

    # Valid public URL
    assert sanitizer.sanitize_url("https://api.example.com/v1/tools") == "https://api.example.com/v1/tools"

    # Block non-HTTP schemes
    with pytest.raises(ToolSanitizationError, match="Unsupported URL scheme"):
        sanitizer.sanitize_url("file:///etc/passwd")

    # Block loopback
    with pytest.raises(ToolSanitizationError, match="SSRF attempt"):
        sanitizer.sanitize_url("http://localhost:8080/admin")
    with pytest.raises(ToolSanitizationError, match="SSRF attempt"):
        sanitizer.sanitize_url("http://127.0.0.1:9000/metrics")

    # Block AWS / GCP instance metadata
    with pytest.raises(ToolSanitizationError, match="SSRF attempt"):
        sanitizer.sanitize_url("http://169.254.169.254/latest/meta-data/")
    with pytest.raises(ToolSanitizationError, match="SSRF attempt"):
        sanitizer.sanitize_url("http://metadata.google.internal/computeMetadata/v1/")

    # Block private network
    with pytest.raises(ToolSanitizationError, match="SSRF attempt"):
        sanitizer.sanitize_url("http://10.0.0.5/internal/api")
    with pytest.raises(ToolSanitizationError, match="SSRF attempt"):
        sanitizer.sanitize_url("http://192.168.1.1/router")


def test_sanitize_payload_recursion_and_types() -> None:
    sanitizer = ToolArgumentSanitizer(max_recursion_depth=3)

    clean_payload = {
        "tool": "search",
        "args": {
            "query": "documentation",
            "filters": ["tag1", "tag2"],
        },
    }
    sanitized = sanitizer.sanitize_payload(clean_payload)
    assert sanitized["tool"] == "search"
    assert sanitized["args"]["query"] == "documentation"

    # Deep recursive JSON bomb
    deep_payload: dict[str, Any] = {"a": {"b": {"c": {"d": {"e": 1}}}}}
    with pytest.raises(ToolSanitizationError, match="maximum recursion depth"):
        sanitizer.sanitize_payload(deep_payload)

    # Null byte in key
    with pytest.raises(ToolSanitizationError, match="Invalid dictionary key"):
        sanitizer.sanitize_payload({"bad\x00key": "val"})
