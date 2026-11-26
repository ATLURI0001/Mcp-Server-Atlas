"""Tests for tool_schema_contract."""
import pytest
from scripts.tool_schema_contract import validate_tool_schema


def test_validate_tool_schema():
    validate_tool_schema({"name": "search", "inputSchema": {"type": "object"}})
    with pytest.raises(ValueError):
        validate_tool_schema({"name": ""})
