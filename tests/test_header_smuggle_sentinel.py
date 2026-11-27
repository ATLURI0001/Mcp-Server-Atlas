"""Tests for header_smuggle_sentinel."""
import pytest
from scripts.header_smuggle_sentinel import assert_clean_mcp_header


def test_header_smuggle_sentinel():
    assert_clean_mcp_header("X-Mcp-Session", "abc123")
    with pytest.raises(ValueError):
        assert_clean_mcp_header("X-Bad", "val\r\nEvil: 1")
