"""Unit tests for TransportBenchmark and transport speedup calculations."""

import sys
from pathlib import Path
import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from latency_benchmark import TransportBenchmark


def test_analyze_latencies_clean_distribution():
    benchmark = TransportBenchmark(timeout_ms=1000.0)
    samples = [10.0, 12.0, 11.0, 15.0, 10.5, 9.8, 14.2]

    profile = benchmark.analyze_latencies("stdio", samples)
    assert profile["transport"] == "stdio"
    assert profile["total_samples"] == 7
    assert profile["successful_samples"] == 7
    assert profile["timeout_count"] == 0
    assert profile["loss_rate"] == 0.0
    assert profile["mean_ms"] > 10.0
    assert profile["median_ms"] > 0.0
    assert profile["p95_ms"] >= profile["median_ms"]
    assert profile["max_jitter_ms"] > 0.0


def test_analyze_latencies_with_timeouts_and_nans():
    benchmark = TransportBenchmark(timeout_ms=100.0)
    # 2 timeouts (150ms, 200ms) out of 5 valid
    samples = [20.0, 30.0, 150.0, float("nan"), 200.0, -5.0, 25.0]

    profile = benchmark.analyze_latencies("sse", samples)
    assert profile["transport"] == "sse"
    assert profile["successful_samples"] == 3  # 20.0, 30.0, 25.0
    assert profile["timeout_count"] == 2
    # Total samples passed was 7
    assert profile["total_samples"] == 7
    assert profile["loss_rate"] == round(2 / 7, 4)


def test_empty_samples_handling():
    benchmark = TransportBenchmark()
    profile = benchmark.analyze_latencies("http", [])
    assert profile["total_samples"] == 0
    assert profile["mean_ms"] == 0.0
    assert profile["loss_rate"] == 0.0


def test_compare_transports_speedup_calculation():
    benchmark = TransportBenchmark()
    stdio_samples = [10.0, 10.0, 10.0]  # mean 10ms
    sse_samples = [50.0, 50.0, 50.0]    # mean 50ms
    http_samples = [5.0, 5.0, 5.0]      # mean 5ms (2x faster than stdio)

    res_stdio = benchmark.analyze_latencies("stdio", stdio_samples)
    res_sse = benchmark.analyze_latencies("sse", sse_samples)
    res_http = benchmark.analyze_latencies("http", http_samples)

    comparison = benchmark.compare_transports([res_stdio, res_sse, res_http], baseline_transport="stdio")
    assert comparison["baseline"] == "stdio"

    profiles = {p["transport"]: p for p in comparison["profiles"]}
    assert profiles["stdio"]["speedup_vs_baseline"] == 1.0
    assert profiles["sse"]["speedup_vs_baseline"] == 0.2  # 10 / 50 = 0.2
    assert profiles["http"]["speedup_vs_baseline"] == 2.0 # 10 / 5 = 2.0


def test_invalid_transport_name_validation():
    benchmark = TransportBenchmark()
    with pytest.raises(ValueError, match="non-empty string"):
        benchmark.analyze_latencies("", [10.0])
