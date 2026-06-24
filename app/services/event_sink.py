"""Domain event sink abstraction.

A small, transport-agnostic interface the service uses to announce noteworthy
domain events (provider failures, circuit-open rejections) without depending on
Kafka — or any messaging — directly. The Kafka layer provides an implementation;
the default is a no-op so the REST path stays broker-free.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SearchEventSink(Protocol):
    """Receives domain events emitted during a search."""

    def on_provider_failure(self, *, provider: str, query: str, error: str) -> None:
        """Called when an individual provider fails during aggregation."""

    def on_circuit_open(self, *, provider: str, query: str) -> None:
        """Called when a provider call is rejected by an open circuit."""


class NullEventSink:
    """A sink that ignores every event (default when no sink is wired)."""

    def on_provider_failure(self, *, provider: str, query: str, error: str) -> None:
        """Ignore the event."""

    def on_circuit_open(self, *, provider: str, query: str) -> None:
        """Ignore the event."""
