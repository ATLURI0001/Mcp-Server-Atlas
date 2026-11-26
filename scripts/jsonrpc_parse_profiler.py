"""JSON-RPC message parsing throughput profiler."""
import json
import time


def benchmark_jsonrpc_parse(payload: str, iterations: int = 500) -> float:
    start = time.perf_counter()
    for _ in range(iterations):
        _ = json.loads(payload)
    elapsed = max(time.perf_counter() - start, 1e-9)
    return round(iterations / elapsed, 2)
