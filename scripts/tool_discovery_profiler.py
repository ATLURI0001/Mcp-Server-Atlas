"""Tool discovery lookup throughput profiler."""
import time


class ToolDiscoveryProfiler:
    """Benchmarks MCP tool registry lookup throughput."""

    def __init__(self, registry: dict[str, dict]) -> None:
        self._registry = registry

    def run_benchmark(self, keys: list[str], iterations: int = 500) -> dict[str, float]:
        start = time.perf_counter()
        hits = 0
        for _ in range(iterations):
            for k in keys:
                if k in self._registry:
                    hits += 1
        elapsed = max(time.perf_counter() - start, 1e-9)
        return {"iterations": iterations, "hits": hits, "ops_per_s": round((iterations * len(keys)) / elapsed, 2)}
