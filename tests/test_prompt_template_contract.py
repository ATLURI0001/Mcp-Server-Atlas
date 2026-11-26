from scripts.prompt_template_contract import (
    ArgumentType,
    PromptArgumentSchema,
    PromptDefinition,
    PromptRole,
    PromptTemplateContract,
    PromptTemplateMessage,
)


def test_successful_prompt_render():
    prompt = PromptDefinition(
        name="code_review",
        description="Review code snippet",
        arguments=[
            PromptArgumentSchema(name="language", required=True, arg_type=ArgumentType.STRING),
            PromptArgumentSchema(name="max_issues", required=False, arg_type=ArgumentType.INTEGER, default_value=5),
        ],
        messages=[
            PromptTemplateMessage(role=PromptRole.SYSTEM, template="You are an expert in {language}."),
            PromptTemplateMessage(role=PromptRole.USER, template="Review code, maximum {max_issues} issues."),
        ],
    )
    contract = PromptTemplateContract(prompt)
    result = contract.bind_and_render({"language": "Python"})

    assert result.valid is True
    assert len(result.rendered_messages) == 2
    assert result.rendered_messages[0]["content"] == "You are an expert in Python."
    assert result.rendered_messages[1]["content"] == "Review code, maximum 5 issues."


def test_undeclared_template_variable():
    prompt = PromptDefinition(
        name="broken_prompt",
        description="Missing argument in schema",
        arguments=[PromptArgumentSchema(name="known_arg")],
        messages=[PromptTemplateMessage(role=PromptRole.USER, template="Hello {unknown_arg}!")],
    )
    contract = PromptTemplateContract(prompt)
    result = contract.bind_and_render({"known_arg": "test"})

    assert result.valid is False
    assert "ERR_UNDECLARED_TEMPLATE_VAR" in result.error_codes
    assert result.diagnostics[0].argument == "unknown_arg"


def test_missing_required_argument():
    prompt = PromptDefinition(
        name="test_prompt",
        description="Testing missing reqs",
        arguments=[
            PromptArgumentSchema(name="target", required=True),
        ],
        messages=[PromptTemplateMessage(role=PromptRole.USER, template="Scan {target}")],
    )
    contract = PromptTemplateContract(prompt)
    result = contract.bind_and_render({})

    assert result.valid is False
    assert "ERR_MISSING_REQUIRED_ARG" in result.error_codes


def test_type_mismatch_and_coercion():
    prompt = PromptDefinition(
        name="typed_prompt",
        description="Typed arguments",
        arguments=[
            PromptArgumentSchema(name="count", arg_type=ArgumentType.INTEGER),
            PromptArgumentSchema(name="enable_flag", arg_type=ArgumentType.BOOLEAN),
        ],
        messages=[PromptTemplateMessage(role=PromptRole.USER, template="Count: {count}, Flag: {enable_flag}")],
    )
    contract = PromptTemplateContract(prompt)

    # Valid coercion
    res_ok = contract.bind_and_render({"count": "42", "enable_flag": "yes"})
    assert res_ok.valid is True
    assert res_ok.rendered_messages[0]["content"] == "Count: 42, Flag: True"

    # Invalid type
    res_err = contract.bind_and_render({"count": "not-a-number", "enable_flag": "true"})
    assert res_err.valid is False
    assert "ERR_TYPE_MISMATCH" in res_err.error_codes


def test_injection_pattern_rejection():
    prompt = PromptDefinition(
        name="secure_prompt",
        description="Checking injection mitigation",
        arguments=[PromptArgumentSchema(name="user_input")],
        messages=[PromptTemplateMessage(role=PromptRole.USER, template="Echo: {user_input}")],
    )
    contract = PromptTemplateContract(prompt)
    result = contract.bind_and_render({"user_input": "attempting __proto__ pollution"})

    assert result.valid is False
    assert "ERR_INJECTION_PATTERN_DETECTED" in result.error_codes


def test_unexpected_extra_arguments():
    prompt = PromptDefinition(
        name="strict_prompt",
        description="Strict checking",
        arguments=[PromptArgumentSchema(name="expected")],
        messages=[PromptTemplateMessage(role=PromptRole.USER, template="{expected}")],
    )
    contract = PromptTemplateContract(prompt, strict_extra_args=True)
    result = contract.bind_and_render({"expected": "val", "malicious_extra": "hack"})

    assert result.valid is False
    assert "ERR_UNEXPECTED_ARGUMENT" in result.error_codes
