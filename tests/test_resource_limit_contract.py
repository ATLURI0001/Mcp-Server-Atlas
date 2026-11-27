import pytest
from scripts.resource_limit_contract import validate_resource_limit


def test_resource_limit_contract():
    validate_resource_limit(5)
    with pytest.raises(ValueError, match="exceeds limit"):
        validate_resource_limit(11)
