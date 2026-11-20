"""Multi-dimensional MCP Capability & Transport Negotiator.

Evaluates server-client protocol compatibility, transport fallback chains,
and detects tool namespace collisions across composite multi-server topologies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class McpTransport(str, Enum):
    STDIO = "stdio"
    SSE = "sse"
    STREAM = "stream"
    WEBSOCKET = "websocket"


SUPPORTED_CAPABILITIES = {
    "tools",
    "prompts",
    "resources",
    "logging",
    "roots",
    "sampling",
}


@dataclass(frozen=True)
class ServerProfile:
    server_id: str
    protocol_version: str  # e.g., "2024-11-05" or "1.0.0"
    transports: List[McpTransport]
    capabilities: Set[str]
    tools_exposed: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ClientRequirement:
    required_capabilities: Set[str]
    preferred_transports: List[McpTransport]
    min_protocol_version: Optional[str] = None


@dataclass(frozen=True)
class NegotiationResult:
    compatible: bool
    negotiated_transport: Optional[McpTransport]
    matched_capabilities: Set[str]
    missing_capabilities: Set[str]
    compatibility_score: float  # [0.0, 1.0]


@dataclass(frozen=True)
class TopologyValidationReport:
    server_count: int
    namespace_collisions: Dict[str, List[str]]  # tool_name -> [server_ids]
    has_conflicts: bool
    global_capabilities: Set[str]


def parse_protocol_date(version_str: str) -> Tuple[int, int, int]:
    """Parse YYYY-MM-DD or standard SemVer for monotonic comparison."""
    m_date = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", version_str.strip())
    if m_date:
        return int(m_date.group(1)), int(m_date.group(2)), int(m_date.group(3))
    m_semver = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?$", version_str.strip())
    if m_semver:
        return int(m_semver.group(1)), int(m_semver.group(2)), int(m_semver.group(3) or 0)
    return (0, 0, 0)


def negotiate_server_compatibility(
    server: ServerProfile,
    client: ClientRequirement,
) -> NegotiationResult:
    """Evaluate whether server satisfies client capability and transport criteria."""
    if client.min_protocol_version:
        s_ver = parse_protocol_date(server.protocol_version)
        c_ver = parse_protocol_date(client.min_protocol_version)
        if s_ver < c_ver:
            return NegotiationResult(
                compatible=False,
                negotiated_transport=None,
                matched_capabilities=set(),
                missing_capabilities=client.required_capabilities,
                compatibility_score=0.0,
            )

    matched = server.capabilities.intersection(client.required_capabilities)
    missing = client.required_capabilities.difference(server.capabilities)

    negotiated_transport: Optional[McpTransport] = None
    for pref in client.preferred_transports:
        if pref in server.transports:
            negotiated_transport = pref
            break

    is_compatible = (len(missing) == 0) and (negotiated_transport is not None)

    total_req = len(client.required_capabilities)
    cap_score = (len(matched) / total_req) if total_req > 0 else 1.0
    transport_score = 1.0 if negotiated_transport is not None else 0.0
    overall_score = round(0.7 * cap_score + 0.3 * transport_score, 2)

    return NegotiationResult(
        compatible=is_compatible,
        negotiated_transport=negotiated_transport,
        matched_capabilities=matched,
        missing_capabilities=missing,
        compatibility_score=overall_score if is_compatible else min(overall_score, 0.4),
    )


def validate_topology(servers: List[ServerProfile]) -> TopologyValidationReport:
    """Validate multi-server composition and detect tool naming collisions."""
    tool_map: Dict[str, List[str]] = {}
    global_caps: Set[str] = set()

    for s in servers:
        global_caps.update(s.capabilities)
        for t in s.tools_exposed:
            tool_name = t.strip()
            if tool_name not in tool_map:
                tool_map[tool_name] = []
            tool_map[tool_name].append(s.server_id)

    collisions = {t: s_list for t, s_list in tool_map.items() if len(s_list) > 1}

    return TopologyValidationReport(
        server_count=len(servers),
        namespace_collisions=collisions,
        has_conflicts=len(collisions) > 0,
        global_capabilities=global_caps,
    )
