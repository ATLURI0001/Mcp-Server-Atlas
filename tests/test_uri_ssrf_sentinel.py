"""Tests for uri_ssrf_sentinel."""
import pytest
from scripts.uri_ssrf_sentinel import assert_safe_resource_uri


def test_uri_ssrf_sentinel():
    assert_safe_resource_uri("https://example.com/resource")
    with pytest.raises(ValueError):
        assert_safe_resource_uri("http://169.254.169.254/latest/meta-data/")
