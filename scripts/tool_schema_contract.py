"""MCP tool schema contract validator."""


def validate_tool_schema(schema: dict) -> None:
    if not isinstance(schema, dict):
        raise ValueError("tool schema must be a dict")
    if not schema.get("name") or not isinstance(schema["name"], str):
        raise ValueError("tool schema requires non-empty string 'name'")
    if "inputSchema" not in schema or not isinstance(schema["inputSchema"], dict):
        raise ValueError("tool schema requires dict 'inputSchema'")
