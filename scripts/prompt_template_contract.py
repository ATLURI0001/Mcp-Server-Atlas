"""MCP Prompt Template & Argument Substitution Contract Validator.

Enforces schema contracts for Model Context Protocol (MCP) prompt definitions,
argument declarations, type coercion boundaries, and injection-safe rendering.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set


class ArgumentType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    JSON = "json"


class PromptRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


@dataclass(frozen=True)
class PromptArgumentSchema:
    name: str
    description: str = ""
    required: bool = True
    arg_type: ArgumentType = ArgumentType.STRING
    default_value: Optional[Any] = None


@dataclass(frozen=True)
class PromptTemplateMessage:
    role: PromptRole
    template: str


@dataclass(frozen=True)
class PromptDefinition:
    name: str
    description: str
    arguments: List[PromptArgumentSchema] = field(default_factory=list)
    messages: List[PromptTemplateMessage] = field(default_factory=list)


@dataclass
class ValidationDiagnostic:
    code: str
    message: str
    argument: Optional[str] = None


@dataclass
class PromptContractResult:
    valid: bool
    rendered_messages: List[Dict[str, str]] = field(default_factory=list)
    diagnostics: List[ValidationDiagnostic] = field(default_factory=list)

    @property
    def error_codes(self) -> List[str]:
        return [d.code for d in self.diagnostics]


class PromptTemplateContract:
    """Validates prompt definitions and binds arguments under strict contract invariants."""

    _VAR_REGEX = re.compile(r"\{\{?([a-zA-Z_][a-zA-Z0-9_]*)\}?\}")
    _DANGEROUS_PATTERNS = ["__proto__", "__globals__", "\x00"]

    def __init__(self, definition: PromptDefinition, strict_extra_args: bool = True) -> None:
        self.definition = definition
        self.strict_extra_args = strict_extra_args
        self._arg_map: Dict[str, PromptArgumentSchema] = {
            arg.name: arg for arg in definition.arguments
        }

    def validate_schema(self) -> List[ValidationDiagnostic]:
        """Validates that all variables referenced in template strings exist in argument schemas."""
        diagnostics: List[ValidationDiagnostic] = []
        declared_args = set(self._arg_map.keys())
        referenced_args: Set[str] = set()

        for idx, msg in enumerate(self.definition.messages):
            matches = set(self._VAR_REGEX.findall(msg.template))
            referenced_args.update(matches)

        undeclared = referenced_args - declared_args
        for var in sorted(undeclared):
            diagnostics.append(
                ValidationDiagnostic(
                    code="ERR_UNDECLARED_TEMPLATE_VAR",
                    message=f"Template references variable '{var}' which is not in declared schema",
                    argument=var,
                )
            )

        return diagnostics

    def bind_and_render(self, provided_args: Dict[str, Any]) -> PromptContractResult:
        """Validates input arguments and safely renders prompt messages."""
        diagnostics = self.validate_schema()
        if diagnostics:
            return PromptContractResult(valid=False, diagnostics=diagnostics)

        # Check for dangerous patterns
        for key, val in provided_args.items():
            str_val = str(val)
            for danger in self._DANGEROUS_PATTERNS:
                if danger in key or danger in str_val:
                    diagnostics.append(
                        ValidationDiagnostic(
                            code="ERR_INJECTION_PATTERN_DETECTED",
                            message=f"Dangerous pattern '{danger}' detected in argument '{key}'",
                            argument=key,
                        )
                    )

        if diagnostics:
            return PromptContractResult(valid=False, diagnostics=diagnostics)

        # Check extra arguments if strict
        if self.strict_extra_args:
            extra_keys = set(provided_args.keys()) - set(self._arg_map.keys())
            for extra in sorted(extra_keys):
                diagnostics.append(
                    ValidationDiagnostic(
                        code="ERR_UNEXPECTED_ARGUMENT",
                        message=f"Provided argument '{extra}' is not declared in prompt schema",
                        argument=extra,
                    )
                )

        bound_args: Dict[str, Any] = {}

        # Validate required arguments and defaults
        for name, schema in self._arg_map.items():
            if name in provided_args:
                val = provided_args[name]
                coerced, type_diag = self._validate_and_coerce_type(schema, val)
                if type_diag:
                    diagnostics.append(type_diag)
                else:
                    bound_args[name] = coerced
            elif schema.required:
                if schema.default_value is not None:
                    bound_args[name] = schema.default_value
                else:
                    diagnostics.append(
                        ValidationDiagnostic(
                            code="ERR_MISSING_REQUIRED_ARG",
                            message=f"Missing required argument '{name}'",
                            argument=name,
                        )
                    )
            else:
                bound_args[name] = schema.default_value if schema.default_value is not None else ""

        if diagnostics:
            return PromptContractResult(valid=False, diagnostics=diagnostics)

        # Render messages
        rendered: List[Dict[str, str]] = []
        for msg in self.definition.messages:
            content = self._render_string(msg.template, bound_args)
            rendered.append({"role": msg.role.value, "content": content})

        return PromptContractResult(valid=True, rendered_messages=rendered)

    def _validate_and_coerce_type(
        self, schema: PromptArgumentSchema, value: Any
    ) -> tuple[Any, Optional[ValidationDiagnostic]]:
        target_type = schema.arg_type

        if target_type == ArgumentType.STRING:
            return str(value), None

        if target_type == ArgumentType.INTEGER:
            if isinstance(value, bool):
                return None, ValidationDiagnostic(
                    code="ERR_TYPE_MISMATCH",
                    message=f"Argument '{schema.name}' expected integer, received boolean",
                    argument=schema.name,
                )
            try:
                return int(value), None
            except (ValueError, TypeError):
                return None, ValidationDiagnostic(
                    code="ERR_TYPE_MISMATCH",
                    message=f"Argument '{schema.name}' cannot be coerced to integer: {value}",
                    argument=schema.name,
                )

        if target_type == ArgumentType.NUMBER:
            if isinstance(value, bool):
                return None, ValidationDiagnostic(
                    code="ERR_TYPE_MISMATCH",
                    message=f"Argument '{schema.name}' expected number, received boolean",
                    argument=schema.name,
                )
            try:
                return float(value), None
            except (ValueError, TypeError):
                return None, ValidationDiagnostic(
                    code="ERR_TYPE_MISMATCH",
                    message=f"Argument '{schema.name}' cannot be coerced to float: {value}",
                    argument=schema.name,
                )

        if target_type == ArgumentType.BOOLEAN:
            if isinstance(value, bool):
                return value, None
            if str(value).lower() in ("true", "1", "yes"):
                return True, None
            if str(value).lower() in ("false", "0", "no"):
                return False, None
            return None, ValidationDiagnostic(
                code="ERR_TYPE_MISMATCH",
                message=f"Argument '{schema.name}' cannot be coerced to boolean: {value}",
                argument=schema.name,
            )

        return value, None

    def _render_string(self, template: str, args: Dict[str, Any]) -> str:
        def repl(match: re.Match[str]) -> str:
            var_name = match.group(1)
            val = args.get(var_name, "")
            return str(val)

        return self._VAR_REGEX.sub(repl, template)
