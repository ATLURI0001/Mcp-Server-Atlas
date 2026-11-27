"""Mcp-Server-Atlas: schema version contract validator."""


def validate_schema_version(version: str) -> None:
    """Raise ValueError if version is not in MAJOR.MINOR.PATCH format."""
    parts = version.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError(f"invalid schema version: {version!r}")
