"""
MCP Server Capabilities Ingress Contract & Feature Matrix Validator.

Validates Model Context Protocol (MCP) server capability declarations, protocol version
negotiation, server metadata, and feature matrices against strict formal invariants.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set


class CapabilityContractViolationCode(str, Enum):
    INVALID_SCHEMA = "ERR_INVALID_CAPABILITIES_SCHEMA"
    UNSUPPORTED_PROTOCOL_VERSION = "ERR_UNSUPPORTED_PROTOCOL_VERSION"
    INVALID_SERVER_INFO = "ERR_INVALID_SERVER_INFO"
    INVALID_CAPABILITY_DECLARATION = "ERR_INVALID_CAPABILITY_DECLARATION"
    DISALLOWED_EXTRA_FIELD = "ERR_DISALLOWED_EXTRA_FIELD"
    MALFORMED_NAME_OR_VERSION = "ERR_MALFORMED_NAME_OR_VERSION"


class MCPCapabilitiesContractError(Exception):
    """Raised when an MCP capabilities payload violates formal contract invariants."""

    def __init__(self, code: CapabilityContractViolationCode, field_name: str, message: str) -> None:
        super().__init__(f"[{code.value}] {field_name}: {message}")
        self.code = code
        self.field_name = field_name
        self.message = message


SUPPORTED_PROTOCOL_VERSIONS: Set[str] = {
    "2024-11-05",
    "2024-10-07",
    "1.0.0",
    "0.1.0",
}

SERVER_NAME_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.\/]{1,64}$")
SEMVER_REGEX = re.compile(r"^\d+\.\d+\.\d+(?:-[a-zA-Z0-9_\-\.]+)?$")
ALLOWED_ROOT_KEYS: Set[str] = {"protocolVersion", "capabilities", "serverInfo", "instructions"}


@dataclass(frozen=True)
class ServerInfo:
    name: str
    version: str


@dataclass(frozen=True)
class ToolsCapability:
    list_changed: bool = False


@dataclass(frozen=True)
class ResourcesCapability:
    subscribe: bool = False
    list_changed: bool = False


@dataclass(frozen=True)
class PromptsCapability:
    list_changed: bool = False


@dataclass(frozen=True)
class LoggingCapability:
    enabled: bool = True


@dataclass(frozen=True)
class ServerCapabilities:
    tools: Optional[ToolsCapability] = None
    resources: Optional[ResourcesCapability] = None
    prompts: Optional[PromptsCapability] = None
    logging: Optional[LoggingCapability] = None
    experimental: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidatedCapabilitiesManifest:
    protocol_version: str
    server_info: ServerInfo
    capabilities: ServerCapabilities
    instructions: Optional[str] = None
    canonical_digest: str = ""


def validate_capabilities_ingress(
    payload: Dict[str, Any],
    strict_mode: bool = True,
) -> ValidatedCapabilitiesManifest:
    """
    Validates an incoming MCP server initialize/capabilities payload against formal invariants.
    """
    if not isinstance(payload, dict):
        raise MCPCapabilitiesContractError(
            CapabilityContractViolationCode.INVALID_SCHEMA,
            "root",
            "Capabilities payload must be a JSON object / dictionary",
        )

    # 1. Strict Root Key Check
    if strict_mode:
        for key in payload.keys():
            if key not in ALLOWED_ROOT_KEYS:
                raise MCPCapabilitiesContractError(
                    CapabilityContractViolationCode.DISALLOWED_EXTRA_FIELD,
                    key,
                    f"Unexpected field '{key}' not permitted in strict MCP capabilities ingress",
                )

    # 2. Protocol Version Validation
    proto_version = payload.get("protocolVersion")
    if not isinstance(proto_version, str) or not proto_version.strip():
        raise MCPCapabilitiesContractError(
            CapabilityContractViolationCode.UNSUPPORTED_PROTOCOL_VERSION,
            "protocolVersion",
            "protocolVersion is required and must be a non-empty string",
        )
    proto_version = proto_version.strip()
    if proto_version not in SUPPORTED_PROTOCOL_VERSIONS:
        raise MCPCapabilitiesContractError(
            CapabilityContractViolationCode.UNSUPPORTED_PROTOCOL_VERSION,
            "protocolVersion",
            f"Unsupported protocol version '{proto_version}'. Allowed: {', '.join(sorted(SUPPORTED_PROTOCOL_VERSIONS))}",
        )

    # 3. Server Info Validation
    server_info_dict = payload.get("serverInfo")
    if not isinstance(server_info_dict, dict):
        raise MCPCapabilitiesContractError(
            CapabilityContractViolationCode.INVALID_SERVER_INFO,
            "serverInfo",
            "serverInfo must be an object with name and version",
        )

    name = str(server_info_dict.get("name", "")).strip()
    if not SERVER_NAME_REGEX.match(name):
        raise MCPCapabilitiesContractError(
            CapabilityContractViolationCode.MALFORMED_NAME_OR_VERSION,
            "serverInfo.name",
            f"Server name '{name}' must match pattern '^[a-zA-Z0-9_\\-\\.\\/]{{1,64}}$'",
        )

    version = str(server_info_dict.get("version", "")).strip()
    if not SEMVER_REGEX.match(version):
        raise MCPCapabilitiesContractError(
            CapabilityContractViolationCode.MALFORMED_NAME_OR_VERSION,
            "serverInfo.version",
            f"Server version '{version}' must conform to semantic versioning (e.g., 1.0.0)",
        )

    server_info = ServerInfo(name=name, version=version)

    # 4. Capabilities Object Validation
    caps_dict = payload.get("capabilities")
    if not isinstance(caps_dict, dict):
        raise MCPCapabilitiesContractError(
            CapabilityContractViolationCode.INVALID_CAPABILITY_DECLARATION,
            "capabilities",
            "capabilities must be an object defining server features",
        )

    tools_cap: Optional[ToolsCapability] = None
    if "tools" in caps_dict:
        t_raw = caps_dict["tools"]
        if not isinstance(t_raw, dict):
            raise MCPCapabilitiesContractError(
                CapabilityContractViolationCode.INVALID_CAPABILITY_DECLARATION,
                "capabilities.tools",
                "tools capability must be an object",
            )
        tools_cap = ToolsCapability(list_changed=bool(t_raw.get("listChanged", False)))

    resources_cap: Optional[ResourcesCapability] = None
    if "resources" in caps_dict:
        r_raw = caps_dict["resources"]
        if not isinstance(r_raw, dict):
            raise MCPCapabilitiesContractError(
                CapabilityContractViolationCode.INVALID_CAPABILITY_DECLARATION,
                "capabilities.resources",
                "resources capability must be an object",
            )
        resources_cap = ResourcesCapability(
            subscribe=bool(r_raw.get("subscribe", False)),
            list_changed=bool(r_raw.get("listChanged", False)),
        )

    prompts_cap: Optional[PromptsCapability] = None
    if "prompts" in caps_dict:
        p_raw = caps_dict["prompts"]
        if not isinstance(p_raw, dict):
            raise MCPCapabilitiesContractError(
                CapabilityContractViolationCode.INVALID_CAPABILITY_DECLARATION,
                "capabilities.prompts",
                "prompts capability must be an object",
            )
        prompts_cap = PromptsCapability(list_changed=bool(p_raw.get("listChanged", False)))

    logging_cap: Optional[LoggingCapability] = None
    if "logging" in caps_dict:
        l_raw = caps_dict["logging"]
        if not isinstance(l_raw, dict):
            raise MCPCapabilitiesContractError(
                CapabilityContractViolationCode.INVALID_CAPABILITY_DECLARATION,
                "capabilities.logging",
                "logging capability must be an object",
            )
        logging_cap = LoggingCapability(enabled=True)

    experimental_map = caps_dict.get("experimental", {})
    if not isinstance(experimental_map, dict):
        raise MCPCapabilitiesContractError(
            CapabilityContractViolationCode.INVALID_CAPABILITY_DECLARATION,
            "capabilities.experimental",
            "experimental capability must be an object/dict",
        )

    capabilities = ServerCapabilities(
        tools=tools_cap,
        resources=resources_cap,
        prompts=prompts_cap,
        logging=logging_cap,
        experimental=dict(experimental_map),
    )

    instructions = payload.get("instructions")
    if instructions is not None and not isinstance(instructions, str):
        raise MCPCapabilitiesContractError(
            CapabilityContractViolationCode.INVALID_SCHEMA,
            "instructions",
            "instructions must be a string if provided",
        )

    # 5. Deterministic Digest Computation
    canonical_dict = {
        "proto": proto_version,
        "name": server_info.name,
        "version": server_info.version,
        "tools": bool(tools_cap),
        "resources": bool(resources_cap),
        "prompts": bool(prompts_cap),
        "logging": bool(logging_cap),
        "experimental": sorted(list(experimental_map.keys())),
    }
    canonical_json = json.dumps(canonical_dict, sort_keys=True)
    digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    return ValidatedCapabilitiesManifest(
        protocol_version=proto_version,
        server_info=server_info,
        capabilities=capabilities,
        instructions=instructions,
        canonical_digest=digest,
    )
