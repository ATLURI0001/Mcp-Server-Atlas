"""MCP HTTP header smuggling sentinel."""


def assert_clean_mcp_header(name: str, value: str) -> None:
    if any(c in name for c in ("\r", "\n", ":")):
        raise ValueError("sentinel violation: invalid character in MCP header name")
    if "\r" in value or "\n" in value:
        raise ValueError("sentinel violation: CRLF in MCP header value")
