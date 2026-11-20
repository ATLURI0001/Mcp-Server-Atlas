import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from capability_matrix import (
    ClientRequirement,
    McpTransport,
    ServerProfile,
    negotiate_server_compatibility,
    parse_protocol_date,
    validate_topology,
)


def test_parse_protocol_date():
    assert parse_protocol_date("2024-11-05") == (2024, 11, 5)
    assert parse_protocol_date("2024-03-01") < parse_protocol_date("2024-11-05")
    assert parse_protocol_date("1.2.3") == (1, 2, 3)
    assert parse_protocol_date("2.0") == (2, 0, 0)
    assert parse_protocol_date("invalid") == (0, 0, 0)


def test_negotiate_full_compatibility():
    server = ServerProfile(
        server_id="postgres-mcp",
        protocol_version="2024-11-05",
        transports=[McpTransport.STDIO, McpTransport.SSE],
        capabilities={"tools", "resources", "prompts"},
        tools_exposed=["query_db", "get_schema"],
    )

    client = ClientRequirement(
        required_capabilities={"tools", "resources"},
        preferred_transports=[McpTransport.STDIO, McpTransport.SSE],
        min_protocol_version="2024-10-01",
    )

    result = negotiate_server_compatibility(server, client)
    assert result.compatible is True
    assert result.negotiated_transport == McpTransport.STDIO
    assert result.matched_capabilities == {"tools", "resources"}
    assert len(result.missing_capabilities) == 0
    assert result.compatibility_score == 1.0


def test_negotiate_transport_fallback():
    server = ServerProfile(
        server_id="remote-mcp",
        protocol_version="2024-11-05",
        transports=[McpTransport.SSE, McpTransport.WEBSOCKET],
        capabilities={"tools", "logging"},
    )

    # Client prefers STDIO, then SSE
    client = ClientRequirement(
        required_capabilities={"tools"},
        preferred_transports=[McpTransport.STDIO, McpTransport.SSE],
    )

    result = negotiate_server_compatibility(server, client)
    assert result.compatible is True
    assert result.negotiated_transport == McpTransport.SSE
    assert result.matched_capabilities == {"tools"}


def test_negotiate_missing_capabilities():
    server = ServerProfile(
        server_id="simple-mcp",
        protocol_version="2024-11-05",
        transports=[McpTransport.STDIO],
        capabilities={"tools"},
    )

    client = ClientRequirement(
        required_capabilities={"tools", "sampling"},
        preferred_transports=[McpTransport.STDIO],
    )

    result = negotiate_server_compatibility(server, client)
    assert result.compatible is False
    assert result.missing_capabilities == {"sampling"}
    assert result.compatibility_score <= 0.4


def test_negotiate_protocol_version_outdated():
    server = ServerProfile(
        server_id="legacy-mcp",
        protocol_version="2024-05-01",
        transports=[McpTransport.STDIO],
        capabilities={"tools"},
    )

    client = ClientRequirement(
        required_capabilities={"tools"},
        preferred_transports=[McpTransport.STDIO],
        min_protocol_version="2024-11-05",
    )

    result = negotiate_server_compatibility(server, client)
    assert result.compatible is False
    assert result.compatibility_score == 0.0


def test_validate_topology_detects_tool_collisions():
    server_a = ServerProfile(
        server_id="server-a",
        protocol_version="2024-11-05",
        transports=[McpTransport.STDIO],
        capabilities={"tools"},
        tools_exposed=["fetch_weather", "lookup_geo"],
    )

    server_b = ServerProfile(
        server_id="server-b",
        protocol_version="2024-11-05",
        transports=[McpTransport.STDIO],
        capabilities={"tools", "resources"},
        tools_exposed=["lookup_geo", "calculate_route"],
    )

    report = validate_topology([server_a, server_b])
    assert report.server_count == 2
    assert report.has_conflicts is True
    assert "lookup_geo" in report.namespace_collisions
    assert sorted(report.namespace_collisions["lookup_geo"]) == ["server-a", "server-b"]
    assert "fetch_weather" not in report.namespace_collisions
    assert report.global_capabilities == {"tools", "resources"}
