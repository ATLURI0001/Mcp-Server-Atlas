"""MCP resource metadata contract validator."""


def validate_resource_meta(meta: dict) -> None:
    if not isinstance(meta, dict):
        raise ValueError("resource metadata must be a dict")
    if not meta.get("uri") or not isinstance(meta["uri"], str):
        raise ValueError("resource metadata requires non-empty string 'uri'")
    if not meta.get("mimeType") or not isinstance(meta["mimeType"], str):
        raise ValueError("resource metadata requires non-empty string 'mimeType'")
