"""Tests for resource_meta_contract."""
import pytest
from scripts.resource_meta_contract import validate_resource_meta


def test_resource_meta_contract():
    validate_resource_meta({"uri": "file:///a.txt", "mimeType": "text/plain"})
    with pytest.raises(ValueError):
        validate_resource_meta({"uri": "", "mimeType": "text/plain"})
