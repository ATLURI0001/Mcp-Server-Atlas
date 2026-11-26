"""Tests for MCP Protocol Framing Benchmark Profiler."""

import pytest
from scripts.protocol_framing_benchmark import (
    FramingBenchmarkResult,
    FramingLatencyStats,
    ProtocolFramingBenchmarkProfiler,
)


def test_profiler_synthetic_payload_generation():
    profiler = ProtocolFramingBenchmarkProfiler()

    small = profiler.generate_synthetic_payload("small")
    assert small["jsonrpc"] == "2.0"
    assert small["method"] == "tools/list"

    medium = profiler.generate_synthetic_payload("medium")
    assert medium["method"] == "tools/call"
    assert "arguments" in medium["params"]

    large = profiler.generate_synthetic_payload("large")
    assert "servers" in large["result"]
    assert len(large["result"]["servers"]) == 250

    with pytest.raises(ValueError):
        profiler.generate_synthetic_payload("invalid_type")


def test_profiler_roundtrip_execution():
    profiler = ProtocolFramingBenchmarkProfiler()
    res = profiler.profile_framing_roundtrip(payload_type="small", iterations=50)

    assert res.test_name == "roundtrip-small"
    assert res.iteration_count == 50
    assert res.frames_per_sec > 0
    assert res.throughput_mb_per_sec > 0
    assert res.encode_stats_us.sample_count == 50
    assert res.decode_stats_us.sample_count == 50
    assert res.encode_stats_us.min_us <= res.encode_stats_us.max_us
    assert res.decode_stats_us.p50_us <= res.decode_stats_us.p99_us


def test_profiler_streaming_chunked_fragmentation():
    profiler = ProtocolFramingBenchmarkProfiler()

    # Stream across 64-byte chunks
    res64 = profiler.profile_streaming_chunks(chunk_size_bytes=64, num_frames=20)
    assert res64["chunk_size_bytes"] == 64
    assert res64["frames_expected"] == 20
    assert res64["frames_decoded"] == 20
    assert res64["deframing_integrity"] is True

    # Stream across 4KB chunks
    res4k = profiler.profile_streaming_chunks(chunk_size_bytes=4096, num_frames=20)
    assert res4k["frames_decoded"] == 20
    assert res4k["deframing_integrity"] is True


def test_profiler_stats_computation():
    latencies = [10.0, 20.0, 30.0, 40.0, 50.0]
    stats = ProtocolFramingBenchmarkProfiler._compute_stats(latencies)

    assert stats.sample_count == 5
    assert stats.min_us == 10.0
    assert stats.max_us == 50.0
    assert stats.mean_us == 30.0
    assert stats.p50_us == 30.0


def test_profiler_format_markdown_report():
    profiler = ProtocolFramingBenchmarkProfiler()
    res = profiler.profile_framing_roundtrip(payload_type="small", iterations=20)
    report = profiler.format_markdown_report([res])

    assert "# MCP Protocol Framing Benchmark Profiler Report" in report
    assert "`roundtrip-small`" in report
    assert "Microsecond Latency Breakdown" in report
    assert "Encode" in report
    assert "Decode" in report
