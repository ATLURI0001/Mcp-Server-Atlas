import pytest
from scripts.capabilities_contract import (
    CapabilityContractViolationCode,
    MCPCapabilitiesContractError,
    validate_capabilities_ingress,
)


def test_valid_capabilities_manifest_all_features():
    payload = {
        "protocolVersion": "2024-11-05",
        "serverInfo": {
            "name": "filesystem-mcp-server",
            "version": "1.2.0",
        },
        "capabilities": {
            "tools": {"listChanged": True},
            "resources": {"subscribe": True, "listChanged": True},
            "prompts": {"listChanged": False},
            "logging": {},
            "experimental": {"customTelemetry": {"v": 1}},
        },
        "instructions": "Use these tools to inspect filesystem assets safely.",
    }

    manifest = validate_capabilities_ingress(payload, strict_mode=True)
    assert manifest.protocol_version == "2024-11-05"
    assert manifest.server_info.name == "filesystem-mcp-server"
    assert manifest.server_info.version == "1.2.0"
    assert manifest.capabilities.tools is not None
    assert manifest.capabilities.tools.list_changed is True
    assert manifest.capabilities.resources is not None
    assert manifest.capabilities.resources.subscribe is True
    assert manifest.capabilities.prompts is not None
    assert manifest.capabilities.logging is not None
    assert "customTelemetry" in manifest.capabilities.experimental
    assert len(manifest.canonical_digest) == 64


def test_unsupported_protocol_version():
    payload = {
        "protocolVersion": "1999-01-01",
        "serverInfo": {"name": "test-srv", "version": "1.0.0"},
        "capabilities": {},
    }
    with pytest.raises(MCPCapabilitiesContractError) as exc_info:
        validate_capabilities_ingress(payload)
    assert exc_info.value.code == CapabilityContractViolationCode.UNSUPPORTED_PROTOCOL_VERSION
    assert exc_info.value.field_name == "protocolVersion"


def test_malformed_server_info_name_and_version():
    # Invalid name (spaces, special symbols)
    p1 = {
        "protocolVersion": "2024-11-05",
        "serverInfo": {"name": "bad server name!", "version": "1.0.0"},
        "capabilities": {},
    }
    with pytest.raises(MCPCapabilitiesContractError) as exc1:
        validate_capabilities_ingress(p1)
    assert exc1.value.code == CapabilityContractViolationCode.MALFORMED_NAME_OR_VERSION
    assert exc1.value.field_name == "serverInfo.name"

    # Non-semver version
    p2 = {
        "protocolVersion": "2024-11-05",
        "serverInfo": {"name": "good-server", "version": "v1-latest"},
        "capabilities": {},
    }
    with pytest.raises(MCPCapabilitiesContractError) as exc2:
        validate_capabilities_ingress(p2)
    assert exc2.value.code == CapabilityContractViolationCode.MALFORMED_NAME_OR_VERSION
    assert exc2.value.field_name == "serverInfo.version"


def test_invalid_capability_shape_rejection():
    # Tools passed as string instead of dict
    p = {
        "protocolVersion": "2024-11-05",
        "serverInfo": {"name": "test-srv", "version": "1.0.0"},
        "capabilities": {
            "tools": "enabled",  # Invalid type
        },
    }
    with pytest.raises(MCPCapabilitiesContractError) as exc:
        validate_capabilities_ingress(p)
    assert exc.value.code == CapabilityContractViolationCode.INVALID_CAPABILITY_DECLARATION
    assert exc.value.field_name == "capabilities.tools"


def test_strict_mode_disallowed_extra_field():
    payload = {
        "protocolVersion": "2024-11-05",
        "serverInfo": {"name": "test-srv", "version": "1.0.0"},
        "capabilities": {},
        "extraForbiddenField": 12345,
    }

    # Fails in strict mode
    with pytest.raises(MCPCapabilitiesContractError) as exc:
        validate_capabilities_ingress(payload, strict_mode=True)
    assert exc.value.code == CapabilityContractViolationCode.DISALLOWED_EXTRA_FIELD
    assert exc.value.field_name == "extraForbiddenField"

    # Succeeds in non-strict mode
    manifest = validate_capabilities_ingress(payload, strict_mode=False)
    assert manifest.server_info.name == "test-srv"


def test_canonical_digest_determinism():
    p1 = {
        "protocolVersion": "2024-11-05",
        "serverInfo": {"name": "deterministic-server", "version": "2.0.0"},
        "capabilities": {"tools": {}, "logging": {}},
    }
    p2 = {
        "serverInfo": {"version": "2.0.0", "name": "deterministic-server"},
        "capabilities": {"logging": {}, "tools": {}},
        "protocolVersion": "2024-11-05",
    }
    m1 = validate_capabilities_ingress(p1)
    m2 = validate_capabilities_ingress(p2)
    assert m1.canonical_digest == m2.canonical_digest
