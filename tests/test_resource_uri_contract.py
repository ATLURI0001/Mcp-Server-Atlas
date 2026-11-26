"""
Unit tests for MCP Resource URI & Subscription Boundary Contract.
"""

import pytest

from scripts.resource_uri_contract import (
    InvalidCursorError,
    InvalidResourceURIError,
    MCPResourceMetadata,
    ResourceContractViolationError,
    ResourceURIContract,
    SubscriptionLimitExceededError,
)


def test_nominal_uri_validation():
    contract = ResourceURIContract()

    assert contract.validate_uri("resource://catalog/models/v1") == "resource://catalog/models/v1"
    assert contract.validate_uri("file:///var/log/system.log") == "file:///var/log/system.log"
    assert contract.validate_uri("custom://tenant-123/stream") == "custom://tenant-123/stream"


def test_uri_path_traversal_rejection():
    contract = ResourceURIContract()

    with pytest.raises(InvalidResourceURIError) as exc_info:
        contract.validate_uri("file:///etc/../../passwd")
    assert "path traversal" in str(exc_info.value)

    with pytest.raises(InvalidResourceURIError):
        contract.validate_uri("resource://repo/branch/./secret")


def test_unauthorized_uri_scheme():
    contract = ResourceURIContract()

    with pytest.raises(InvalidResourceURIError) as exc_info:
        contract.validate_uri("javascript://alert(1)")
    assert "scheme 'javascript' is not permitted" in str(exc_info.value)


def test_max_uri_length_boundary():
    contract = ResourceURIContract(max_uri_length=60)
    valid_uri = "resource://short/path"
    assert contract.validate_uri(valid_uri) == valid_uri

    long_uri = "resource://" + "a" * 60
    with pytest.raises(InvalidResourceURIError) as exc_info:
        contract.validate_uri(long_uri)
    assert "exceeds max allowed boundary" in str(exc_info.value)


def test_validate_resource_metadata():
    contract = ResourceURIContract()

    meta = contract.validate_resource({
        "uri": "resource://schema/user_profile",
        "name": "UserProfileSchema",
        "mimeType": "application/json",
        "description": "User profile JSON schema definition",
        "sizeBytes": 1024,
    })

    assert isinstance(meta, MCPResourceMetadata)
    assert meta.name == "UserProfileSchema"
    assert meta.mime_type == "application/json"
    assert meta.size_bytes == 1024

    d = meta.to_dict()
    assert d["mimeType"] == "application/json"


def test_invalid_mime_type():
    contract = ResourceURIContract()
    with pytest.raises(ResourceContractViolationError) as exc_info:
        contract.validate_resource({
            "uri": "resource://schema/invalid",
            "name": "Invalid",
            "mimeType": "invalid-mime-format",
        })
    assert "Invalid MIME type format" in str(exc_info.value)


def test_subscription_limits_and_lifecycle():
    contract = ResourceURIContract(max_subscriptions_per_session=3)
    session = "session-client-42"

    contract.subscribe_resource(session, "resource://topic/1")
    contract.subscribe_resource(session, "resource://topic/2")
    contract.subscribe_resource(session, "resource://topic/3")

    # Duplicate subscription does not count twice
    contract.subscribe_resource(session, "resource://topic/3")
    assert len(contract.get_subscriptions(session)) == 3

    # Exceeding limit
    with pytest.raises(SubscriptionLimitExceededError):
        contract.subscribe_resource(session, "resource://topic/4")

    # Unsubscribe
    assert contract.unsubscribe_resource(session, "resource://topic/2") is True
    assert len(contract.get_subscriptions(session)) == 2

    # Now can subscribe topic 4
    contract.subscribe_resource(session, "resource://topic/4")
    assert len(contract.get_subscriptions(session)) == 3


def test_cursor_encoding_and_decoding():
    contract = ResourceURIContract()

    cursor = contract.encode_cursor(50)
    assert isinstance(cursor, str)
    assert contract.decode_cursor(cursor) == 50

    with pytest.raises(InvalidCursorError):
        contract.decode_cursor("not-base64!!")

    with pytest.raises(InvalidCursorError):
        contract.decode_cursor("bWFsb2Zvcm1lZA==")
