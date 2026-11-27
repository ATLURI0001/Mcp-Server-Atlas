"""Mcp-Server-Atlas: resource limit contract – caps concurrent tool calls."""


def validate_resource_limit(concurrent: int, max_limit: int = 10) -> None:
    if concurrent < 0 or concurrent > max_limit:
        raise ValueError(
            f"concurrent tool calls {concurrent} exceeds limit {max_limit}"
        )
