"""Multi-Transport MCP Latency Benchmark & Statistical Transport Profiler.

Benchmarks round-trip RPC response times across MCP transports (stdio, SSE, HTTP)
and computes percentiles, jitter, and transport speedup metrics.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional


class TransportBenchmark:
    """Profiles and compares latency distributions across MCP transport mechanisms."""

    def __init__(self, timeout_ms: float = 5000.0):
        self.timeout_ms = timeout_ms

    def analyze_latencies(self, transport_name: str, samples_ms: List[float]) -> Dict[str, object]:
        """Calculates statistical latency distribution and jitter profile."""
        if not transport_name or not isinstance(transport_name, str):
            raise ValueError("transport_name must be a non-empty string")

        total_samples = len(samples_ms)
        if total_samples == 0:
            return {
                "transport": transport_name,
                "total_samples": 0,
                "successful_samples": 0,
                "timeout_count": 0,
                "loss_rate": 0.0,
                "mean_ms": 0.0,
                "median_ms": 0.0,
                "p95_ms": 0.0,
                "p99_ms": 0.0,
                "max_jitter_ms": 0.0,
                "std_dev_ms": 0.0,
            }

        valid_samples: List[float] = []
        timeout_count = 0

        for s in samples_ms:
            if not isinstance(s, (int, float)) or math.isnan(s) or s < 0:
                continue
            if s >= self.timeout_ms:
                timeout_count += 1
            else:
                valid_samples.append(float(s))

        loss_rate = round(timeout_count / total_samples, 4)
        n = len(valid_samples)

        if n == 0:
            return {
                "transport": transport_name,
                "total_samples": total_samples,
                "successful_samples": 0,
                "timeout_count": timeout_count,
                "loss_rate": loss_rate,
                "mean_ms": 0.0,
                "median_ms": 0.0,
                "p95_ms": 0.0,
                "p99_ms": 0.0,
                "max_jitter_ms": 0.0,
                "std_dev_ms": 0.0,
            }

        sorted_samples = sorted(valid_samples)
        mean_ms = sum(sorted_samples) / n
        variance = sum((x - mean_ms) ** 2 for x in sorted_samples) / n
        std_dev_ms = math.sqrt(variance)

        # Compute maximum inter-sample jitter
        max_jitter_ms = 0.0
        if len(valid_samples) > 1:
            for i in range(1, len(valid_samples)):
                diff = abs(valid_samples[i] - valid_samples[i - 1])
                if diff > max_jitter_ms:
                    max_jitter_ms = diff

        return {
            "transport": transport_name,
            "total_samples": total_samples,
            "successful_samples": n,
            "timeout_count": timeout_count,
            "loss_rate": loss_rate,
            "mean_ms": round(mean_ms, 2),
            "median_ms": round(self._percentile(sorted_samples, 0.50), 2),
            "p95_ms": round(self._percentile(sorted_samples, 0.95), 2),
            "p99_ms": round(self._percentile(sorted_samples, 0.99), 2),
            "max_jitter_ms": round(max_jitter_ms, 2),
            "std_dev_ms": round(std_dev_ms, 2),
        }

    def compare_transports(self, results: List[Dict[str, object]], baseline_transport: str = "stdio") -> Dict[str, object]:
        """Compares target transports against baseline and determines relative speedups."""
        baseline_profile = next((r for r in results if r.get("transport") == baseline_transport), None)
        baseline_mean = float(baseline_profile["mean_ms"]) if baseline_profile and float(baseline_profile["mean_ms"]) > 0 else None

        comparisons: List[Dict[str, object]] = []
        for r in results:
            t_name = str(r.get("transport", ""))
            mean_ms = float(r.get("mean_ms", 0.0))

            speedup = None
            if baseline_mean and mean_ms > 0:
                speedup = round(baseline_mean / mean_ms, 2)

            comparisons.append({
                "transport": t_name,
                "mean_ms": mean_ms,
                "median_ms": r.get("median_ms"),
                "p95_ms": r.get("p95_ms"),
                "loss_rate": r.get("loss_rate"),
                "speedup_vs_baseline": speedup,
            })

        return {
            "baseline": baseline_transport,
            "profiles": comparisons,
        }

    @staticmethod
    def _percentile(sorted_data: List[float], p: float) -> float:
        if not sorted_data:
            return 0.0
        idx = int(round(p * (len(sorted_data) - 1)))
        idx = max(0, min(len(sorted_data) - 1, idx))
        return sorted_data[idx]
