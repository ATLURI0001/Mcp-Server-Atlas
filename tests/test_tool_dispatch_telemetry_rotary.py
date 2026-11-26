import pytest
from scripts.tool_dispatch_telemetry_rotary import (
    ToolDispatchTelemetryRotary,
)


def test_empty_rotary():
    rotary = ToolDispatchTelemetryRotary(capacity=10)
    summary = rotary.get_summary()

    assert summary.sample_count == 0
    assert summary.total_records == 0
    assert summary.error_rate_percent == 0.0


def test_single_tool_dispatch():
    rotary = ToolDispatchTelemetryRotary(capacity=10)
    rotary.record(
        tool_name="get_weather",
        request_bytes=120,
        response_bytes=850,
        latency_ms=45.2,
        success=True,
    )

    summary = rotary.get_summary()
    assert summary.sample_count == 1
    assert summary.total_records == 1
    assert summary.p50_latency_ms == 45.2
    assert summary.p50_response_bytes == 850
    assert summary.tool_frequency.get("get_weather") == 1
    assert summary.error_rate_percent == 0.0


def test_wrap_around_and_error_rate():
    rotary = ToolDispatchTelemetryRotary(capacity=5)

    # Record 10 entries with 2 failures
    for i in range(1, 11):
        is_success = (i % 5 != 0)
        err = "ERR_TIMEOUT" if not is_success else None
        rotary.record(
            tool_name="query_db" if i % 2 == 0 else "fetch_api",
            request_bytes=100 * i,
            response_bytes=200 * i,
            latency_ms=10.0 * i,
            success=is_success,
            error_code=err,
        )

    summary = rotary.get_summary()
    assert summary.sample_count == 5
    assert summary.total_records == 10
    assert summary.p50_latency_ms >= 60.0
    assert summary.error_rate_percent > 0.0


def test_invalid_arguments():
    with pytest.raises(ValueError):
        ToolDispatchTelemetryRotary(capacity=0)

    rotary = ToolDispatchTelemetryRotary(capacity=5)
    with pytest.raises(ValueError):
        rotary.record("", 10, 10, 5.0)
