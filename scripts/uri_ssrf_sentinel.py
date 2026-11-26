"""MCP resource URI SSRF sentinel."""
from urllib.parse import urlparse


def assert_safe_resource_uri(uri: str) -> None:
    parsed = urlparse(uri)
    if parsed.scheme not in ("https", "http", "file"):
        raise ValueError(f"sentinel violation: unsupported URI scheme '{parsed.scheme}'")
    if parsed.hostname in ("169.254.169.254", "metadata.google.internal"):
        raise ValueError(f"sentinel violation: blocked metadata host '{parsed.hostname}'")
