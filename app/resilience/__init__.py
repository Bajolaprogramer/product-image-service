"""Resilience primitives.

Reusable, provider-independent building blocks for tolerating downstream
failures. Currently a single-file circuit breaker; future additions (retries,
bulkheads) belong here too.
"""

from app.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
)

__all__ = ["CircuitBreaker", "CircuitOpenError", "CircuitState"]
