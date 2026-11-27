"""Circuit breaker for stdio transport pipe operations."""
import time


class StdioCircuitOpenError(RuntimeError):
    """Raised when stdio pipe circuit breaker is open."""


class StdioPipeCircuitBreaker:
    def __init__(self, threshold: int = 3, cooldown_s: float = 10.0) -> None:
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self.failures = 0
        self.open_until = 0.0

    def call(self, fn):
        if time.monotonic() < self.open_until:
            raise StdioCircuitOpenError("stdio pipe circuit open")
        try:
            res = fn()
        except Exception:
            self.failures += 1
            if self.failures >= self.threshold:
                self.open_until = time.monotonic() + self.cooldown_s
                self.failures = 0
            raise
        self.failures = 0
        return res
