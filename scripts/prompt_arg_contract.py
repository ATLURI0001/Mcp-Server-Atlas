"""MCP prompt argument schema contract validator."""


def validate_prompt_arg(arg: dict) -> None:
    if not isinstance(arg, dict):
        raise ValueError("prompt arg must be a dict")
    if not arg.get("name") or not isinstance(arg["name"], str):
        raise ValueError("prompt arg requires non-empty string 'name'")
    if "required" in arg and not isinstance(arg["required"], bool):
        raise ValueError("prompt arg 'required' must be a boolean")
