"""Transport connection timeout and heartbeat failure fallback circuit breaker.

Provides robust stateful fault tolerance across MCP transports (Stdio, SSE, WebSocket, HTTP).
Guards against cascading failures, process hangs, and deadlocked subprocess channels by
tripping to OPEN state when heartbeat or connection timeout thresholds are exceeded,
transparently delegating to fallback handlers.
"""

from __future__ import annotations

import enum
import time
from typing import Any, Callable, Dict, Optional, Tuple


class CircuitState(str, enum.Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerOpenError(Exception):
    """Raised when an operation is attempted while the circuit breaker is OPEN."""

    def __init__(self, message: str, retry_after: float):
        super().__init__(message)
        self.retry_after = retry_after


class TransportCircuitBreaker:
    """Stateful circuit breaker with heartbeat monitoring and fallback execution."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout_sec: float = 10.0,
        heartbeat_timeout_sec: float = 15.0,
        half_open_max_trials: int = 3,
        fallback_handler: Optional[Callable[[str, Any], Any]] = None,
    ):
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if recovery_timeout_sec <= 0:
            raise ValueError("recovery_timeout_sec must be > 0")

        self.failure_threshold = failure_threshold
        self.recovery_timeout_sec = recovery_timeout_sec
        self.heartbeat_timeout_sec = heartbeat_timeout_sec
        self.half_open_max_trials = half_open_max_trials
        self.fallback_handler = fallback_handler

        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._half_open_successes = 0
        self._opened_at: Optional[float] = None
        self._last_failure_reason: Optional[str] = None

        # Heartbeat tracking: session_id -> last_seen_epoch_sec
        self._heartbeats: Dict[str, float] = {}

        # Telemetry metrics
        self._total_calls = 0
        self._fallback_calls = 0
        self._state_transitions = 0

    @property
    def state(self) -> CircuitState:
        """Evaluates current state, automatically transitioning OPEN -> HALF_OPEN after timeout."""
        if self._state == CircuitState.OPEN and self._opened_at is not None:
            now = time.monotonic()
            if now - self._opened_at >= self.recovery_timeout_sec:
                self._state = CircuitState.HALF_OPEN
                self._half_open_successes = 0
                self._state_transitions += 1
        return self._state

    def trip(self, reason: str = "Threshold exceeded") -> None:
        """Manually trips the circuit breaker to OPEN."""
        if self._state != CircuitState.OPEN:
            self._state = CircuitState.OPEN
            self._opened_at = time.monotonic()
            self._last_failure_reason = reason
            self._state_transitions += 1

    def reset(self) -> None:
        """Resets the circuit breaker to CLOSED."""
        if self._state != CircuitState.CLOSED:
            self._state = CircuitState.CLOSED
            self._consecutive_failures = 0
            self._half_open_successes = 0
            self._opened_at = None
            self._state_transitions += 1

    def record_heartbeat(self, session_id: str, timestamp: Optional[float] = None) -> None:
        """Registers a heartbeat arrival for a transport session."""
        self._heartbeats[session_id] = timestamp if timestamp is not None else time.monotonic()

    def check_heartbeat(self, session_id: str, current_time: Optional[float] = None) -> bool:
        """Checks if a transport session heartbeat is alive. Trips circuit if dead."""
        now = current_time if current_time is not None else time.monotonic()
        last_hb = self._heartbeats.get(session_id)
        if last_hb is None:
            # Unseen session
            return False
        
        elapsed = now - last_hb
        if elapsed > self.heartbeat_timeout_sec:
            self.record_failure(f"Heartbeat timeout on session '{session_id}' ({elapsed:.2f}s > {self.heartbeat_timeout_sec}s)")
            return False
        return True

    def record_success(self) -> None:
        """Records a successful operation."""
        curr_state = self.state
        if curr_state == CircuitState.HALF_OPEN:
            self._half_open_successes += 1
            if self._half_open_successes >= self.half_open_max_trials:
                self.reset()
        elif curr_state == CircuitState.CLOSED:
            self._consecutive_failures = 0

    def record_failure(self, reason: str = "Operation failed") -> None:
        """Records a failed operation. Trips circuit if threshold reached."""
        self._consecutive_failures += 1
        self._last_failure_reason = reason

        curr_state = self.state
        if curr_state in (CircuitState.HALF_OPEN, CircuitState.CLOSED):
            if self._consecutive_failures >= self.failure_threshold or curr_state == CircuitState.HALF_OPEN:
                self.trip(reason)

    def execute(self, action_name: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Tuple[Any, bool]:
        """Executes a transport operation protected by the circuit breaker.

        Returns:
            Tuple[Any, bool]: (result, used_fallback)
        """
        self._total_calls += 1
        curr_state = self.state

        if curr_state == CircuitState.OPEN:
            remaining = max(0.0, self.recovery_timeout_sec - (time.monotonic() - (self._opened_at or 0.0)))
            if self.fallback_handler is not None:
                self._fallback_calls += 1
                return self.fallback_handler(action_name, *args, **kwargs), True
            raise CircuitBreakerOpenError(
                f"Circuit is OPEN for action '{action_name}'. Last failure: {self._last_failure_reason}",
                retry_after=remaining,
            )

        try:
            result = fn(*args, **kwargs)
            self.record_success()
            return result, False
        except Exception as exc:
            self.record_failure(f"Exception during '{action_name}': {exc}")
            if self.fallback_handler is not None:
                self._fallback_calls += 1
                return self.fallback_handler(action_name, *args, **kwargs), True
            raise

    def get_metrics(self) -> Dict[str, Any]:
        """Returns runtime diagnostic metrics."""
        return {
            "state": self.state.value,
            "consecutive_failures": self._consecutive_failures,
            "total_calls": self._total_calls,
            "fallback_calls": self._fallback_calls,
            "state_transitions": self._state_transitions,
            "last_failure_reason": self._last_failure_reason,
            "tracked_sessions": len(self._heartbeats),
        }
