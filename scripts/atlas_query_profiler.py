"""atlas_query_profiler.py – tracks query execution times."""


class AtlasQueryProfiler:
    def __init__(self):
        self._times: list[float] = []

    def record(self, ms: float) -> None:
        self._times.append(ms)

    def max_ms(self) -> float:
        return max(self._times) if self._times else 0.0
