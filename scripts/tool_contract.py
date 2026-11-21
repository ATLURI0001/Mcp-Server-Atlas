"""MCP Tool Parameter Schema Contract & Argument Sanitization Engine.

Enforces structural schema validation on tools/call arguments against tools/list
inputSchema contracts, performs safe scalar type coercion, and guards against
path traversal and shell injection vulnerabilities.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple, Union


class SchemaContractError(ValueError):
    """Raised when an argument payload violates its tool schema contract."""
    pass


SHELL_INJECTION_PATTERN = re.compile(r"[;&|`$><\n\r]")


@dataclass
class ToolContractResult:
    is_valid: bool
    sanitized_arguments: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    coerced_fields: List[str] = field(default_factory=list)


def coerce_scalar_type(val: Any, expected_type: str) -> Tuple[Any, bool]:
    """Attempt safe, non-lossy coercion of scalar types."""
    if expected_type == "string":
        if isinstance(val, (int, float, bool)):
            return str(val), True
        return val, False

    if expected_type == "integer":
        if isinstance(val, int) and not isinstance(val, bool):
            return val, False
        if isinstance(val, str) and re.match(r"^-?\d+$", val.strip()):
            return int(val.strip()), True
        return val, False

    if expected_type == "number":
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return float(val), False
        if isinstance(val, str):
            try:
                return float(val.strip()), True
            except ValueError:
                return val, False
        return val, False

    if expected_type == "boolean":
        if isinstance(val, bool):
            return val, False
        if isinstance(val, str):
            s = val.strip().lower()
            if s in ("true", "1", "yes"):
                return True, True
            if s in ("false", "0", "no"):
                return False, True
        return val, False

    return val, False


def sanitize_argument_value(val: Any, sanitize_shell: bool = False, sanitize_path: bool = False) -> Any:
    """Sanitize string values against null bytes, traversal, and shell escapes."""
    if not isinstance(val, str):
        return val

    if "\0" in val:
        raise SchemaContractError("Argument value contains illegal null byte sequence")

    if sanitize_path:
        norm = val.replace("\\", "/")
        if ".." in norm.split("/"):
            raise SchemaContractError(f"Argument value '{val}' contains directory traversal sequence ('..')")

    if sanitize_shell:
        if SHELL_INJECTION_PATTERN.search(val):
            raise SchemaContractError(f"Argument value '{val}' contains dangerous shell metacharacters")

    return val


def validate_and_sanitize_tool_arguments(
    input_schema: Dict[str, Any],
    arguments: Dict[str, Any],
    allow_coercion: bool = True,
    strict_shell_check: bool = False,
    path_fields: Optional[Set[str]] = None,
) -> ToolContractResult:
    """Validate incoming tools/call arguments against tool inputSchema."""
    if not isinstance(input_schema, dict):
        return ToolContractResult(is_valid=False, errors=["inputSchema must be a dictionary"])

    if not isinstance(arguments, dict):
        return ToolContractResult(is_valid=False, errors=["arguments must be a dictionary"])

    schema_type = input_schema.get("type", "object")
    if schema_type != "object":
        return ToolContractResult(is_valid=False, errors=[f"Expected root schema type 'object', got '{schema_type}'"])

    errors: List[str] = []
    coerced_fields: List[str] = []
    sanitized_args: Dict[str, Any] = {}

    properties: Dict[str, Any] = input_schema.get("properties", {})
    required: List[str] = input_schema.get("required", [])
    additional_allowed: bool = input_schema.get("additionalProperties", True)
    path_keys = path_fields or set()

    # 1. Check required properties
    for req_field in required:
        if req_field not in arguments or arguments[req_field] is None:
            errors.append(f"Missing required argument: '{req_field}'")

    # 2. Check additional properties
    if not additional_allowed:
        for arg_key in arguments:
            if arg_key not in properties:
                errors.append(f"Unexpected argument not permitted by schema: '{arg_key}'")

    # 3. Validate and coerce each argument
    for arg_key, arg_val in arguments.items():
        prop_spec = properties.get(arg_key)
        if prop_spec is None:
            # Undeclared property allowed if additionalProperties is true
            sanitized_args[arg_key] = arg_val
            continue

        expected_type = prop_spec.get("type")
        current_val = arg_val

        # Type checking and coercion
        if expected_type:
            types = expected_type if isinstance(expected_type, list) else [expected_type]
            matched = False
            for t in types:
                if t == "integer" and isinstance(current_val, int) and not isinstance(current_val, bool):
                    matched = True
                    break
                elif t == "number" and isinstance(current_val, (int, float)) and not isinstance(current_val, bool):
                    matched = True
                    break
                elif t == "string" and isinstance(current_val, str):
                    matched = True
                    break
                elif t == "boolean" and isinstance(current_val, bool):
                    matched = True
                    break
                elif t == "array" and isinstance(current_val, list):
                    matched = True
                    break
                elif t == "object" and isinstance(current_val, dict):
                    matched = True
                    break

            if not matched and allow_coercion and len(types) == 1:
                coerced, was_coerced = coerce_scalar_type(current_val, types[0])
                if was_coerced:
                    current_val = coerced
                    coerced_fields.append(arg_key)
                    matched = True

            if not matched:
                errors.append(
                    f"Argument '{arg_key}' expected type {types}, got {type(current_val).__name__}"
                )
                continue

        # Enum check
        if "enum" in prop_spec and current_val not in prop_spec["enum"]:
            errors.append(
                f"Argument '{arg_key}' must be one of {prop_spec['enum']}, got {current_val!r}"
            )

        # String constraints
        if isinstance(current_val, str):
            min_len = prop_spec.get("minLength")
            if min_len is not None and len(current_val) < min_len:
                errors.append(f"Argument '{arg_key}' length ({len(current_val)}) is less than minLength {min_len}")

            max_len = prop_spec.get("maxLength")
            if max_len is not None and len(current_val) > max_len:
                errors.append(f"Argument '{arg_key}' length ({len(current_val)}) exceeds maxLength {max_len}")

            pattern = prop_spec.get("pattern")
            if pattern and not re.search(pattern, current_val):
                errors.append(f"Argument '{arg_key}' does not match pattern {pattern!r}")

            # Sanitization
            try:
                is_path = arg_key in path_keys or "path" in arg_key.lower() or "file" in arg_key.lower()
                current_val = sanitize_argument_value(
                    current_val,
                    sanitize_shell=strict_shell_check,
                    sanitize_path=is_path,
                )
            except SchemaContractError as exc:
                errors.append(f"Argument '{arg_key}' failed sanitization: {exc}")
                continue

        # Numeric constraints
        if isinstance(current_val, (int, float)) and not isinstance(current_val, bool):
            minimum = prop_spec.get("minimum")
            if minimum is not None and current_val < minimum:
                errors.append(f"Argument '{arg_key}' value {current_val} is less than minimum {minimum}")

            maximum = prop_spec.get("maximum")
            if maximum is not None and current_val > maximum:
                errors.append(f"Argument '{arg_key}' value {current_val} exceeds maximum {maximum}")

        sanitized_args[arg_key] = current_val

    is_valid = len(errors) == 0
    return ToolContractResult(
        is_valid=is_valid,
        sanitized_arguments=sanitized_args if is_valid else {},
        errors=errors,
        coerced_fields=coerced_fields,
    )
