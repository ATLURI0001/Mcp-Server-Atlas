import pytest
from scripts.schema_version_contract import validate_schema_version


def test_schema_version_contract():
    validate_schema_version("1.2.3")
    with pytest.raises(ValueError, match="invalid schema version"):
        validate_schema_version("1.2")
