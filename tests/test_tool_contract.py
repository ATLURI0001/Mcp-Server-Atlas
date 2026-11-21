import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from tool_contract import (
    coerce_scalar_type,
    sanitize_argument_value,
    validate_and_sanitize_tool_arguments,
)


def test_coerce_scalar_type():
    val, coerced = coerce_scalar_type("42", "integer")
    assert coerced is True
    assert val == 42

    val, coerced = coerce_scalar_type("3.1415", "number")
    assert coerced is True
    assert abs(val - 3.1415) < 1e-5

    val, coerced = coerce_scalar_type("true", "boolean")
    assert coerced is True
    assert val is True


def test_validate_and_sanitize_tool_arguments_success():
    schema = {
        "type": "object",
        "required": ["repo", "issue_number"],
        "properties": {
            "repo": {"type": "string", "minLength": 3},
            "issue_number": {"type": "integer", "minimum": 1},
            "close_issue": {"type": "boolean"},
            "state": {"type": "string", "enum": ["open", "closed"]},
        },
        "additionalProperties": False,
    }

    # "issue_number" provided as string "42" (should coerce), "close_issue" as "yes" (coerces)
    args = {
        "repo": "owner/repo",
        "issue_number": "42",
        "close_issue": "yes",
        "state": "open",
    }

    res = validate_and_sanitize_tool_arguments(schema, args, allow_coercion=True)
    assert res.is_valid is True
    assert res.sanitized_arguments["repo"] == "owner/repo"
    assert res.sanitized_arguments["issue_number"] == 42
    assert res.sanitized_arguments["close_issue"] is True
    assert "issue_number" in res.coerced_fields
    assert "close_issue" in res.coerced_fields


def test_validate_and_sanitize_missing_required():
    schema = {
        "type": "object",
        "required": ["query"],
        "properties": {"query": {"type": "string"}},
    }
    res = validate_and_sanitize_tool_arguments(schema, {})
    assert res.is_valid is False
    assert any("Missing required argument: 'query'" in e for e in res.errors)


def test_validate_and_sanitize_path_traversal():
    schema = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
        },
    }
    args = {"file_path": "../../../etc/shadow"}
    res = validate_and_sanitize_tool_arguments(schema, args)
    assert res.is_valid is False
    assert any("directory traversal" in e for e in res.errors)


def test_validate_and_sanitize_shell_injection():
    schema = {
        "type": "object",
        "properties": {
            "cmd": {"type": "string"},
        },
    }
    args = {"cmd": "ls; cat /etc/passwd"}
    res = validate_and_sanitize_tool_arguments(schema, args, strict_shell_check=True)
    assert res.is_valid is False
    assert any("dangerous shell metacharacters" in e for e in res.errors)


def test_validate_and_sanitize_unexpected_property():
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "additionalProperties": False,
    }
    res = validate_and_sanitize_tool_arguments(schema, {"name": "test", "extra": "payload"})
    assert res.is_valid is False
    assert any("Unexpected argument not permitted" in e for e in res.errors)
