"""INC-2026-MCP-2201: Stdio JSON-RPC Framing & Partial Read Deadlock Sentinel."""

from __future__ import annotations


class StdioFramingSentinel:
    def __init__(self, max_frame_bytes: int = 1048576) -> None:
        self.max_frame_bytes = max_frame_bytes

    def validate_frame(self, raw_line: str) -> tuple[bool, str]:
        if "\x00" in raw_line:
            return False, "ERR_NULL_BYTE_IN_FRAME"
        if len(raw_line.encode("utf-8")) > self.max_frame_bytes:
            return False, "ERR_FRAME_BUFFER_OVERFLOW"
        stripped = raw_line.strip()
        if not stripped.startswith("{") or not stripped.endswith("}"):
            return False, "ERR_MALFORMED_JSONRPC_BOUNDARY"
        return True, "OK"
