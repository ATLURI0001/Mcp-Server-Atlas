"""Tests for prompt_arg_contract."""
import pytest
from scripts.prompt_arg_contract import validate_prompt_arg


def test_prompt_arg_contract():
    validate_prompt_arg({"name": "topic", "required": True})
    with pytest.raises(ValueError):
        validate_prompt_arg({"name": "", "required": True})
