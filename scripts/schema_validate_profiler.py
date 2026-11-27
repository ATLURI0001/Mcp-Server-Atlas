"""MCP tool argument schema validation throughput profiler."""
import time


def benchmark_schema_validate(required: list[str], payload: dict, iterations: int = 500) -> float:
    start = time.perf_counter()
    for _ in range(iterations):
        _ = all(k in payload for k in required)
    elapsed = max(time.perf_counter() - start, 1e-9)
    return round(iterations / elapsed, 2)
