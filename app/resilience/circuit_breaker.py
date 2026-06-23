"""A reusable, async-first circuit breaker.

The circuit breaker guards calls to an unreliable dependency. After
``failure_threshold`` consecutive failures it "opens" and short-circuits further
calls (raising :class:`CircuitOpenError`) so the failing dependency is given
room to recover and callers fail fast. After ``recovery_timeout_seconds`` it
admits a single probe ("half-open"); the probe's outcome closes the circuit
(success) or re-opens it (failure).

Design notes:
    * **Provider-independent** — it wraps any ``async`` callable and knows
      nothing about HTTP, Open Food Facts, or this project's models.
    * **No third-party dependencies.**
    * **Async-compatible** — :meth:`call` awaits the wrapped operation. State
      transitions happen in synchronous critical sections with no internal
      ``await`` points, so under asyncio's single-threaded model the
      check-and-update logic (including the single half-open probe guard) is
      race-free without locking.
    * **Injectable clock** — ``time_source`` defaults to ``time.monotonic`` but
      can be overridden for deterministic tests.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any, TypeVar

T = TypeVar("T")


class CircuitState(str, Enum):
    """Lifecycle states of a :class:`CircuitBreaker`."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(Exception):
    """Raised by :meth:`CircuitBreaker.call` when the circuit is open.

    Signals that the wrapped operation was deliberately **not** executed because
    the breaker is short-circuiting calls to a failing dependency.
    """


class CircuitBreaker:
    """Guards an async operation, tripping open after repeated failures.

    Attributes are exposed read-only via properties so callers can observe
    breaker health (:attr:`current_state`, :attr:`failure_count`,
    :attr:`success_count`) without mutating it.
    """

    def __init__(
        self,
        failure_threshold: int,
        recovery_timeout_seconds: float,
        *,
        time_source: Callable[[], float] = time.monotonic,
    ) -> None:
        """Configure the breaker.

        Args:
            failure_threshold: Number of consecutive failures (while closed)
                that trips the circuit open. Must be >= 1.
            recovery_timeout_seconds: How long the circuit stays open before
                admitting a probe request.
            time_source: Monotonic clock used for the recovery timeout. Override
                in tests for determinism.

        Raises:
            ValueError: If ``failure_threshold`` is less than 1.
        """

        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")

        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout_seconds
        self._time_source = time_source

        self._state: CircuitState = CircuitState.CLOSED
        self._failure_count: int = 0
        self._success_count: int = 0
        self._opened_at: float | None = None
        self._half_open_in_flight: bool = False

    # --- Observable metrics -------------------------------------------------
    @property
    def current_state(self) -> CircuitState:
        """The breaker's current state."""

        return self._state

    @property
    def failure_count(self) -> int:
        """Consecutive failures since the last success or reset."""

        return self._failure_count

    @property
    def success_count(self) -> int:
        """Total successful calls since the last reset."""

        return self._success_count

    # --- Public API ---------------------------------------------------------
    async def call(
        self,
        operation: Callable[..., Awaitable[T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Execute ``operation`` through the breaker.

        Args:
            operation: The async callable to guard.
            *args: Positional arguments forwarded to ``operation``.
            **kwargs: Keyword arguments forwarded to ``operation``.

        Returns:
            Whatever ``operation`` returns.

        Raises:
            CircuitOpenError: The circuit is open and the call was rejected
                without executing ``operation``.
            Exception: Any exception raised by ``operation`` (after recording
                the failure) is propagated unchanged.
        """

        self._before_call()
        try:
            result = await operation(*args, **kwargs)
        except Exception:
            self._on_failure()
            raise
        self._on_success()
        return result

    def reset(self) -> None:
        """Force the breaker back to a clean, closed state and clear metrics."""

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._opened_at = None
        self._half_open_in_flight = False

    # --- Internal state machine --------------------------------------------
    def _before_call(self) -> None:
        """Admission control: decide whether the call may proceed.

        Lazily transitions OPEN -> HALF_OPEN once the recovery timeout elapses,
        and enforces a single in-flight probe while half-open.

        Raises:
            CircuitOpenError: The call is rejected (open, or a probe is already
                in flight).
        """

        if self._state is CircuitState.OPEN:
            if self._recovery_elapsed():
                self._state = CircuitState.HALF_OPEN
                self._half_open_in_flight = True
                return
            raise CircuitOpenError("Circuit is OPEN; request rejected.")

        if self._state is CircuitState.HALF_OPEN:
            if self._half_open_in_flight:
                raise CircuitOpenError(
                    "Circuit is HALF_OPEN; a probe is already in flight."
                )
            self._half_open_in_flight = True

        # CLOSED: proceed normally.

    def _on_success(self) -> None:
        """Record a success: close the circuit and clear the failure counter."""

        self._success_count += 1
        self._failure_count = 0
        self._half_open_in_flight = False
        self._state = CircuitState.CLOSED
        self._opened_at = None

    def _on_failure(self) -> None:
        """Record a failure, tripping the circuit when warranted.

        A failed half-open probe re-opens immediately; otherwise the circuit
        trips once consecutive failures reach the threshold.
        """

        self._failure_count += 1
        self._half_open_in_flight = False

        if self._state is CircuitState.HALF_OPEN:
            self._trip()
        elif (
            self._state is CircuitState.CLOSED
            and self._failure_count >= self._failure_threshold
        ):
            self._trip()

    def _trip(self) -> None:
        """Open the circuit and stamp the time it opened."""

        self._state = CircuitState.OPEN
        self._opened_at = self._time_source()

    def _recovery_elapsed(self) -> bool:
        """Whether the recovery timeout has passed since the circuit opened."""

        if self._opened_at is None:
            return False
        return (self._time_source() - self._opened_at) >= self._recovery_timeout
