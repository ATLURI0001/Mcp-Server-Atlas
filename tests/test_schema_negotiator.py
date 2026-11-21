import pytest
from scripts.schema_negotiator import (
    SchemaNegotiator,
    ServerCapabilities,
    McpProtocolError,
)

def test_negotiate_version_success():
    negotiator = SchemaNegotiator(supported_versions=["2024-11-05", "2024-10-07"])

    # Single matching version
    v1 = negotiator.negotiate_version("2024-11-05")
    assert v1 == "2024-11-05"

    # List of versions, prefers highest server support
    v2 = negotiator.negotiate_version(["2024-10-07", "2024-11-05"])
    assert v2 == "2024-11-05"

    # Fallback to older supported version
    v3 = negotiator.negotiate_version(["2024-10-07", "2024-05-01"])
    assert v3 == "2024-10-07"


def test_negotiate_version_incompatible_raises():
    negotiator = SchemaNegotiator(supported_versions=["2024-11-05"])

    with pytest.raises(McpProtocolError) as exc_info:
        negotiator.negotiate_version("2023-01-01")

    assert exc_info.value.code == -32602
    assert "no compatible MCP version found" in str(exc_info.value)


def test_handle_initialize_lifecycle():
    negotiator = SchemaNegotiator(
        server_name="atlas-test",
        server_version="2.0.0",
        capabilities=ServerCapabilities(tools=True, prompts=True),
    )

    init_payload = {
        "protocolVersion": "2024-11-05",
        "clientInfo": {"name": "test-client", "version": "1.0"},
        "capabilities": {
            "tools": {},
            "prompts": {},
        },
    }

    res = negotiator.handle_initialize("sess-001", init_payload)
    assert res["protocolVersion"] == "2024-11-05"
    assert res["serverInfo"]["name"] == "atlas-test"
    assert "tools" in res["capabilities"]

    assert negotiator.is_session_initialized("sess-001") is True
    session_res = negotiator.assert_initialized("sess-001")
    assert "tools" in session_res.agreed_capabilities
    assert "prompts" in session_res.agreed_capabilities


def test_handle_initialize_validation_errors():
    negotiator = SchemaNegotiator()

    # Missing clientInfo
    with pytest.raises(McpProtocolError) as exc1:
        negotiator.handle_initialize("sess-err", {"protocolVersion": "2024-11-05"})
    assert exc1.value.code == -32602

    # Missing protocolVersion
    with pytest.raises(McpProtocolError) as exc2:
        negotiator.handle_initialize(
            "sess-err",
            {"clientInfo": {"name": "c", "version": "1"}},
        )
    assert exc2.value.code == -32602

    # Uninitialized session check
    with pytest.raises(McpProtocolError) as exc3:
        negotiator.assert_initialized("unknown-session")
    assert exc3.value.code == -32002
