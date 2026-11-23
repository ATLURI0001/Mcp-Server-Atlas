"""
Mcp-Server-Atlas Fast JSON-RPC Dispatcher & Tool Invocation Benchmark Profiler

Provides low-latency JSON-RPC 2.0 dispatching, batch request processing,
and comprehensive latency percentiles (P50, P90, P95, P99) micro-benchmarking.
"""

from __future__ import annotations

import json
import math
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union


@dataclass
class RpcRequest:
    method: str
    params: Optional[Dict[str, Any]] = None
    id: Optional[Union[str, int]] = None
    jsonrpc: str = "2.0"


@dataclass
class RpcResponse:
    id: Optional[Union[str, int]]
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None
    jsonrpc: str = "2.0"

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"jsonrpc": self.jsonrpc, "id": self.id}
        if self.error is not None:
            data["error"] = self.error
        else:
            data["result"] = self.result
        return data


@dataclass
class BenchmarkProfile:
    name: str
    total_requests: int
    duration_sec: float
    throughput_rps: float
    p50_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    mean_ms: float
    stddev_ms: float
    errors_count: int
    raw_latencies_ms: List[float] = field(default_factory=list, repr=False)


class FastRpcDispatcher:
    """
    High-performance in-memory JSON-RPC 2.0 router with batched dispatch and telemetry.
    """

    def __init__(self) -> None:
        self._handlers: Dict[str, Callable[[Any], Any]] = {}
        self._total_dispatches = 0
        self._total_errors = 0

    def register(self, method: str, handler: Callable[[Any], Any]) -> None:
        self._handlers[method] = handler

    def dispatch_single(self, req: Dict[str, Any]) -> Dict[str, Any]:
        self._total_dispatches += 1
        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params")

        if not isinstance(method, str):
            self._total_errors += 1
            return RpcResponse(
                id=req_id,
                error={"code": -32600, "message": "Invalid Request: missing method string"},
            ).to_dict()

        handler = self._handlers.get(method)
        if handler is None:
            self._total_errors += 1
            return RpcResponse(
                id=req_id,
                error={"code": -32601, "message": f"Method not found: {method}"},
            ).to_dict()

        try:
            if params is None:
                result = handler()
            elif isinstance(params, dict):
                result = handler(**params)
            elif isinstance(params, list):
                result = handler(*params)
            else:
                result = handler(params)

            return RpcResponse(id=req_id, result=result).to_dict()
        except TypeError as e:
            self._total_errors += 1
            return RpcResponse(
                id=req_id,
                error={"code": -32602, "message": f"Invalid params: {str(e)}"},
            ).to_dict()
        except Exception as e:
            self._total_errors += 1
            return RpcResponse(
                id=req_id,
                error={"code": -32000, "message": f"Server error: {str(e)}"},
            ).to_dict()

    def dispatch_batch(self, batch: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not batch:
            return [
                RpcResponse(
                    id=None,
                    error={"code": -32600, "message": "Invalid Request: empty batch array"},
                ).to_dict()
            ]
        return [self.dispatch_single(req) for req in batch]

    def dispatch_raw(self, raw_json: str) -> str:
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError as e:
            self._total_errors += 1
            return json.dumps(
                RpcResponse(
                    id=None,
                    error={"code": -32700, "message": f"Parse error: {str(e)}"},
                ).to_dict()
            )

        if isinstance(parsed, list):
            res = self.dispatch_batch(parsed)
            return json.dumps(res)
        elif isinstance(parsed, dict):
            res = self.dispatch_single(parsed)
            return json.dumps(res)
        else:
            self._total_errors += 1
            return json.dumps(
                RpcResponse(
                    id=None,
                    error={"code": -32600, "message": "Invalid Request: payload must be array or object"},
                ).to_dict()
            )

    @property
    def stats(self) -> Dict[str, int]:
        return {
            "total_dispatches": self._total_dispatches,
            "total_errors": self._total_errors,
            "registered_methods": len(self._handlers),
        }


class RpcBenchmarkProfiler:
    """
    Synthetic benchmarking engine calculating throughput and fine-grained latency distribution.
    """

    @staticmethod
    def calculate_percentiles(latencies_ms: List[float]) -> Dict[str, float]:
        if not latencies_ms:
            return {
                "p50": 0.0,
                "p90": 0.0,
                "p95": 0.0,
                "p99": 0.0,
                "min": 0.0,
                "max": 0.0,
                "mean": 0.0,
                "stddev": 0.0,
            }

        sorted_vals = sorted(latencies_ms)
        n = len(sorted_vals)

        def percentile(p: float) -> float:
            idx = int(math.ceil((p / 100.0) * n)) - 1
            idx = max(0, min(idx, n - 1))
            return sorted_vals[idx]

        mean = statistics.fmean(sorted_vals)
        stddev = statistics.pstdev(sorted_vals) if n > 1 else 0.0

        return {
            "p50": round(percentile(50), 4),
            "p90": round(percentile(90), 4),
            "p95": round(percentile(95), 4),
            "p99": round(percentile(99), 4),
            "min": round(sorted_vals[0], 4),
            "max": round(sorted_vals[-1], 4),
            "mean": round(mean, 4),
            "stddev": round(stddev, 4),
        }

    def run_sequential(
        self,
        dispatcher: FastRpcDispatcher,
        requests: List[Dict[str, Any]],
        iterations: int = 100,
        name: str = "Sequential Dispatch",
    ) -> BenchmarkProfile:
        latencies: List[float] = []
        errors = 0
        total_ops = len(requests) * iterations

        start_total = time.perf_counter()
        for _ in range(iterations):
            for req in requests:
                t0 = time.perf_counter_ns()
                res = dispatcher.dispatch_single(req)
                t1 = time.perf_counter_ns()
                latencies.append((t1 - t0) / 1_000_000.0)
                if "error" in res:
                    errors += 1

        total_duration = time.perf_counter() - start_total
        rps = total_ops / total_duration if total_duration > 0 else 0.0

        pct = self.calculate_percentiles(latencies)
        return BenchmarkProfile(
            name=name,
            total_requests=total_ops,
            duration_sec=round(total_duration, 4),
            throughput_rps=round(rps, 2),
            p50_ms=pct["p50"],
            p90_ms=pct["p90"],
            p95_ms=pct["p95"],
            p99_ms=pct["p99"],
            min_ms=pct["min"],
            max_ms=pct["max"],
            mean_ms=pct["mean"],
            stddev_ms=pct["stddev"],
            errors_count=errors,
            raw_latencies_ms=latencies,
        )

    def run_concurrent(
        self,
        dispatcher: FastRpcDispatcher,
        requests: List[Dict[str, Any]],
        concurrency: int = 4,
        iterations_per_worker: int = 50,
        name: str = "Concurrent Dispatch",
    ) -> BenchmarkProfile:
        latencies: List[float] = []
        errors = 0
        total_ops = len(requests) * iterations_per_worker * concurrency

        def worker_task() -> tuple[List[float], int]:
            worker_latencies: List[float] = []
            worker_errors = 0
            for _ in range(iterations_per_worker):
                for req in requests:
                    t0 = time.perf_counter_ns()
                    res = dispatcher.dispatch_single(req)
                    t1 = time.perf_counter_ns()
                    worker_latencies.append((t1 - t0) / 1_000_000.0)
                    if "error" in res:
                        worker_errors += 1
            return worker_latencies, worker_errors

        start_total = time.perf_counter()
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(worker_task) for _ in range(concurrency)]
            for fut in futures:
                wl, we = fut.result()
                latencies.extend(wl)
                errors += we

        total_duration = time.perf_counter() - start_total
        rps = total_ops / total_duration if total_duration > 0 else 0.0

        pct = self.calculate_percentiles(latencies)
        return BenchmarkProfile(
            name=f"{name} (Workers: {concurrency})",
            total_requests=total_ops,
            duration_sec=round(total_duration, 4),
            throughput_rps=round(rps, 2),
            p50_ms=pct["p50"],
            p90_ms=pct["p90"],
            p95_ms=pct["p95"],
            p99_ms=pct["p99"],
            min_ms=pct["min"],
            max_ms=pct["max"],
            mean_ms=pct["mean"],
            stddev_ms=pct["stddev"],
            errors_count=errors,
            raw_latencies_ms=latencies,
        )

    @staticmethod
    def format_markdown(profile: BenchmarkProfile) -> str:
        return (
            f"| Metric | Value |\n"
            f"| :--- | :--- |\n"
            f"| **Benchmark** | `{profile.name}` |\n"
            f"| **Total Invocations** | `{profile.total_requests:,}` ops |\n"
            f"| **Wall Clock Time** | `{profile.duration_sec:.4f}` s |\n"
            f"| **Throughput** | `{profile.throughput_rps:,.2f}` ops/sec |\n"
            f"| **P50 Latency** | `{profile.p50_ms:.4f}` ms |\n"
            f"| **P90 Latency** | `{profile.p90_ms:.4f}` ms |\n"
            f"| **P95 Latency** | `{profile.p95_ms:.4f}` ms |\n"
            f"| **P99 Latency** | `{profile.p99_ms:.4f}` ms |\n"
            f"| **Min / Max Latency** | `{profile.min_ms:.4f}` ms / `{profile.max_ms:.4f}` ms |\n"
            f"| **Mean / StdDev** | `{profile.mean_ms:.4f}` ms ± `{profile.stddev_ms:.4f}` ms |\n"
            f"| **Errors** | `{profile.errors_count}` |\n"
        )

    @staticmethod
    def assert_sla(profile: BenchmarkProfile, max_p99_ms: float, min_rps: float) -> bool:
        return profile.p99_ms <= max_p99_ms and profile.throughput_rps >= min_rps
