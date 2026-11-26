"""MCP Protocol Framing Benchmark Profiler.

Benchmarks JSON-RPC Content-Length framing, streaming deframing throughput,
chunk fragmentation resistance, and serialization overhead across MCP transport boundaries.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from scripts.transport_framing import TransportFramingCodec


@dataclass
class FramingLatencyStats:
    sample_count: int
    min_us: float
    p50_us: float
    p90_us: float
    p99_us: float
    max_us: float
    mean_us: float


@dataclass
class FramingBenchmarkResult:
    test_name: str
    payload_size_bytes: int
    iteration_count: int
    elapsed_sec: float
    frames_per_sec: float
    throughput_mb_per_sec: float
    encode_stats_us: FramingLatencyStats
    decode_stats_us: FramingLatencyStats


class ProtocolFramingBenchmarkProfiler:
    """Profiles framing/deframing speed, throughput, and latency percentiles."""

    def __init__(self) -> None:
        self.codec = TransportFramingCodec(max_frame_bytes=64 * 1024 * 1024)

    @staticmethod
    def generate_synthetic_payload(payload_type: str = "medium") -> Dict[str, Any]:
        """Generates representative MCP JSON-RPC payloads."""
        if payload_type == "small":
            # Typical ping / heartbeat or tool list request (~150 bytes)
            return {
                "jsonrpc": "2.0",
                "id": 101,
                "method": "tools/list",
                "params": {},
            }
        elif payload_type == "medium":
            # Typical tool invocation with structured arguments (~1.2 KB)
            return {
                "jsonrpc": "2.0",
                "id": 202,
                "method": "tools/call",
                "params": {
                    "name": "read_atlas_catalog",
                    "arguments": {
                        "category": "database",
                        "tags": ["postgres", "vector", "search"],
                        "filter": {"is_active": True, "min_stars": 100},
                        "metadata": {"query_id": "qry-992-alpha-zeta", "client": "mcp-client-py"},
                    },
                },
            }
        elif payload_type == "large":
            # Bulk resource response with embedded data (~64 KB)
            data_blocks = [
                {
                    "server_id": f"srv-{i:04d}",
                    "name": f"server-provider-{i}",
                    "description": f"Managed high-performance connector node {i} for data pipelines.",
                    "capabilities": ["tools", "resources", "prompts", "logging"],
                    "status": "HEALTHY",
                    "latency_ms": 14.2 + (i % 5),
                }
                for i in range(250)
            ]
            return {
                "jsonrpc": "2.0",
                "id": 303,
                "result": {
                    "servers": data_blocks,
                    "total_count": len(data_blocks),
                },
            }
        else:
            raise ValueError(f"Unknown payload_type: {payload_type}")

    def profile_framing_roundtrip(
        self,
        payload_type: str = "medium",
        iterations: int = 500,
    ) -> FramingBenchmarkResult:
        """Profiles encode and decode performance across fixed iterations."""
        payload = self.generate_synthetic_payload(payload_type)
        raw_json_len = len(json.dumps(payload).encode("utf-8"))

        encode_latencies: List[float] = []
        decode_latencies: List[float] = []
        encoded_frames: List[bytes] = []

        # Benchmark Encoding
        t0 = time.perf_counter()
        for _ in range(iterations):
            start_enc = time.perf_counter()
            frame_bytes = self.codec.encode_frame(payload)
            end_enc = time.perf_counter()
            encode_latencies.append((end_enc - start_enc) * 1_000_000.0)  # microseconds
            encoded_frames.append(frame_bytes)

        # Benchmark Decoding
        for frame_bytes in encoded_frames:
            dec_codec = TransportFramingCodec(max_frame_bytes=64 * 1024 * 1024)
            start_dec = time.perf_counter()
            decoded_frames = dec_codec.feed_bytes(frame_bytes)
            end_dec = time.perf_counter()
            decode_latencies.append((end_dec - start_dec) * 1_000_000.0)
            assert len(decoded_frames) == 1

        t_total = time.perf_counter() - t0
        frame_size = len(encoded_frames[0]) if encoded_frames else raw_json_len
        total_bytes = frame_size * iterations * 2  # encode + decode
        fps = (iterations * 2) / max(0.000001, t_total)
        mbps = (total_bytes / (1024.0 * 1024.0)) / max(0.000001, t_total)

        return FramingBenchmarkResult(
            test_name=f"roundtrip-{payload_type}",
            payload_size_bytes=frame_size,
            iteration_count=iterations,
            elapsed_sec=round(t_total, 4),
            frames_per_sec=round(fps, 1),
            throughput_mb_per_sec=round(mbps, 2),
            encode_stats_us=self._compute_stats(encode_latencies),
            decode_stats_us=self._compute_stats(decode_latencies),
        )

    def profile_streaming_chunks(
        self,
        chunk_size_bytes: int = 512,
        num_frames: int = 100,
    ) -> Dict[str, Any]:
        """Profiles deframing streaming fragmentation across arbitrary chunk sizes."""
        payload = self.generate_synthetic_payload("medium")
        frame_bytes = self.codec.encode_frame(payload)
        stream_bytes = frame_bytes * num_frames

        feed_codec = TransportFramingCodec()
        decoded_count = 0

        t0 = time.perf_counter()
        offset = 0
        total_len = len(stream_bytes)

        while offset < total_len:
            end = min(total_len, offset + chunk_size_bytes)
            chunk = stream_bytes[offset:end]
            frames = feed_codec.feed_bytes(chunk)
            decoded_count += len(frames)
            offset = end

        elapsed = time.perf_counter() - t0
        mbps = (total_len / (1024.0 * 1024.0)) / max(0.000001, elapsed)

        return {
            "chunk_size_bytes": chunk_size_bytes,
            "total_bytes_streamed": total_len,
            "frames_expected": num_frames,
            "frames_decoded": decoded_count,
            "elapsed_sec": round(elapsed, 4),
            "throughput_mb_per_sec": round(mbps, 2),
            "deframing_integrity": decoded_count == num_frames,
        }

    @staticmethod
    def _compute_stats(latencies_us: List[float]) -> FramingLatencyStats:
        if not latencies_us:
            return FramingLatencyStats(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

        s = sorted(latencies_us)
        n = len(s)

        def pct(p: float) -> float:
            k = (n - 1) * (p / 100.0)
            f = math.floor(k)
            c = math.ceil(k)
            if f == c:
                return s[int(k)]
            return s[int(f)] * (c - k) + s[int(c)] * (k - f)

        return FramingLatencyStats(
            sample_count=n,
            min_us=round(s[0], 2),
            p50_us=round(pct(50.0), 2),
            p90_us=round(pct(90.0), 2),
            p99_us=round(pct(99.0), 2),
            max_us=round(s[-1], 2),
            mean_us=round(sum(s) / n, 2),
        )

    def format_markdown_report(self, results: List[FramingBenchmarkResult]) -> str:
        """Formats comprehensive benchmark comparison markdown."""
        lines = [
            "# MCP Protocol Framing Benchmark Profiler Report",
            "",
            "| Benchmark Target | Frame Size | Iterations | Total Time | Throughput | Frames / Sec |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        for r in results:
            lines.append(
                f"| `{r.test_name}` | {r.payload_size_bytes} B | {r.iteration_count} | {r.elapsed_sec}s | {r.throughput_mb_per_sec} MB/s | {r.frames_per_sec:,.0f} fps |"
            )

        lines.append("")
        lines.append("### Microsecond Latency Breakdown (Encode / Decode)")
        lines.append("| Target | Phase | Min | P50 (Median) | P90 | P99 | Max | Mean |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

        for r in results:
            enc = r.encode_stats_us
            dec = r.decode_stats_us
            lines.append(
                f"| `{r.test_name}` | Encode | {enc.min_us} µs | {enc.p50_us} µs | {enc.p90_us} µs | {enc.p99_us} µs | {enc.max_us} µs | {enc.mean_us} µs |"
            )
            lines.append(
                f"| `{r.test_name}` | Decode | {dec.min_us} µs | {dec.p50_us} µs | {dec.p90_us} µs | {dec.p99_us} µs | {dec.max_us} µs | {dec.mean_us} µs |"
            )

        return "\n".join(lines)
