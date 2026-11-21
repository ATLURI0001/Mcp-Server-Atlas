"""
MCP Capability Handshake & Protocol Version Negotiation Engine for Mcp-Server-Atlas.
Enforces RFC-compliant JSON-RPC 2.0 initialization framing, schema capability negotiation,
and defensive protocol fallback across supported Model Context Protocol specifications.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


SUPPORTED_MCP_VERSIONS = [
    "2024-11-05",
    "2024-10-07",
    "2024-09-20",
]

DEFAULT_PROTOCOL_VERSION = "2024-11-05"


class McpProtocolError(Exception):
    def __init__(self, code: int, message: str, data: Optional[Any] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_dict(self) -> Dict[str, Any]:
        err: Dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            err["data"] = self.data
        return err


@dataclass
class ServerCapabilities:
    tools: bool = True
    tools_list_changed: bool = True
    resources: bool = True
    resources_subscribe: bool = True
    resources_list_changed: bool = True
    prompts: bool = True
    prompts_list_changed: bool = True
    logging: bool = True

    def to_dict(self) -> Dict[str, Any]:
        caps: Dict[str, Any] = {}
        if self.tools:
            caps["tools"] = {"listChanged": self.tools_list_changed}
        if self.resources:
            caps["resources"] = {
                "subscribe": self.resources_subscribe,
                "listChanged": self.resources_list_changed,
            }
        if self.prompts:
            caps["prompts"] = {"listChanged": self.prompts_list_changed}
        if self.logging:
            caps["logging"] = {}
        return caps


@dataclass
class ClientInfo:
    name: str
    version: str


@dataclass
class NegotiationResult:
    protocol_version: str
    server_capabilities: Dict[str, Any]
    server_info: Dict[str, str]
    agreed_capabilities: Set[str]


class SchemaNegotiator:
    """
    Validates initialize request payloads and negotiates protocol capabilities.
    """

    def __init__(
        self,
        server_name: str = "mcp-server-atlas",
        server_version: str = "1.0.0",
        supported_versions: Optional[List[str]] = None,
        capabilities: Optional[ServerCapabilities] = None,
    ):
        self.server_info = {"name": server_name, "version": server_version}
        self.supported_versions = supported_versions or list(SUPPORTED_MCP_VERSIONS)
        self.capabilities = capabilities or ServerCapabilities()
        self.initialized_sessions: Dict[str, NegotiationResult] = {}

    def negotiate_version(self, client_version_or_list: str | List[str]) -> str:
        """
        Determines the highest mutually supported protocol version.
        """
        if isinstance(client_version_or_list, str):
            client_versions = [client_version_or_list]
        else:
            client_versions = list(client_version_or_list)

        for s_ver in self.supported_versions:
            if s_ver in client_versions:
                return s_ver

        raise McpProtocolError(
            code=-32602,
            message="Protocol version negotiation failed: no compatible MCP version found",
            data={"server_supported": self.supported_versions, "client_offered": client_versions},
        )

    def handle_initialize(
        self,
        session_id: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Processes an MCP 'initialize' JSON-RPC method request.
        """
        if not isinstance(params, dict):
            raise McpProtocolError(code=-32602, message="Invalid params: expected object")

        # Validate clientInfo
        client_info_raw = params.get("clientInfo")
        if not isinstance(client_info_raw, dict) or not client_info_raw.get("name"):
            raise McpProtocolError(
                code=-32602,
                message="Invalid params: clientInfo.name is required",
            )

        client_protocol_version = params.get("protocolVersion")
        if not client_protocol_version or not isinstance(client_protocol_version, str):
            raise McpProtocolError(
                code=-32602,
                message="Invalid params: protocolVersion string is required",
            )

        # Negotiate version
        agreed_version = self.negotiate_version(client_protocol_version)

        # Intersect capabilities
        client_caps = params.get("capabilities", {})
        agreed_caps: Set[str] = set()

        if self.capabilities.tools and "tools" in client_caps:
            agreed_caps.add("tools")
        if self.capabilities.resources and "resources" in client_caps:
            agreed_caps.add("resources")
        if self.capabilities.prompts and "prompts" in client_caps:
            agreed_caps.add("prompts")
        if self.capabilities.logging and "logging" in client_caps:
            agreed_caps.add("logging")

        result = NegotiationResult(
            protocol_version=agreed_version,
            server_capabilities=self.capabilities.to_dict(),
            server_info=self.server_info,
            agreed_capabilities=agreed_caps,
        )
        self.initialized_sessions[session_id] = result

        return {
            "protocolVersion": agreed_version,
            "capabilities": self.capabilities.to_dict(),
            "serverInfo": self.server_info,
        }

    def is_session_initialized(self, session_id: str) -> bool:
        return session_id in self.initialized_sessions

    def assert_initialized(self, session_id: str) -> NegotiationResult:
        if session_id not in self.initialized_sessions:
            raise McpProtocolError(code=-32002, message="Session not initialized")
        return self.initialized_sessions[session_id]
