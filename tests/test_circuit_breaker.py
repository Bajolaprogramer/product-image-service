"""Tests for the circuit breaker and its Open Food Facts integration.

The breaker's clock is injected (``FakeClock``) so recovery-timeout transitions
are exercised deterministically without sleeping. Provider/service integration
uses a counting fake client to prove that an open circuit stops external calls.
"""

from __future__ import annotations

import pytest

from app.clients.open_food_facts_client import (
    OpenFoodFactsImage,
    OpenFoodFactsTimeoutError,
)
from app.models.product_image import ProductImageSearchRequest, SearchStatus
from app.providers.mock_provider import MockProvider
from app.providers.open_food_facts_provider import OpenFoodFactsProvider
from app.providers.registry import ProviderRegistry
from app.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
)
from app.services.product_image_service import ProductImageService

BARCODE = "3017620422003"


class FakeClock:
    """A controllable monotonic clock for deterministic timeout tests."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


async def _ok() -> str:
    """A wrapped operation that always succeeds."""

    return "ok"


async def _boom() -> str:
    """A wrapped operation that always fails."""

    raise RuntimeError("downstream failure")


# --------------------------------------------------------------------------- #
# 1. Circuit opens after threshold failures
# --------------------------------------------------------------------------- #
async def test_circuit_opens_after_threshold_failures() -> None:
    breaker = CircuitBreaker(failure_threshold=3, recovery_timeout_seconds=10)

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await breaker.call(_boom)
    # Below threshold: still closed, counting failures.
    assert breaker.current_state is CircuitState.CLOSED
    assert breaker.failure_count == 2

    with pytest.raises(RuntimeError):
        await breaker.call(_boom)

    # Threshold reached: tripped open.
    assert breaker.current_state is CircuitState.OPEN
    assert breaker.failure_count == 3


# --------------------------------------------------------------------------- #
# 2. Circuit blocks requests while OPEN (wrapped op not executed)
# --------------------------------------------------------------------------- #
async def test_open_circuit_blocks_without_executing_operation() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(
        failure_threshold=1, recovery_timeout_seconds=10, time_source=clock
    )

    with pytest.raises(RuntimeError):
        await breaker.call(_boom)
    assert breaker.current_state is CircuitState.OPEN

    executed = False

    async def _tracked() -> str:
        nonlocal executed
        executed = True
        return "ran"

    with pytest.raises(CircuitOpenError):
        await breaker.call(_tracked)

    assert executed is False  # operation must NOT run while open


# --------------------------------------------------------------------------- #
# 3 & 4. Recovery timeout -> HALF_OPEN, then successful probe -> CLOSED
# --------------------------------------------------------------------------- #
async def test_recovery_timeout_half_open_then_success_closes() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(
        failure_threshold=1, recovery_timeout_seconds=10, time_source=clock
    )

    with pytest.raises(RuntimeError):
        await breaker.call(_boom)
    assert breaker.current_state is CircuitState.OPEN

    # Not yet elapsed: still rejecting.
    clock.advance(9)
    with pytest.raises(CircuitOpenError):
        await breaker.call(_ok)

    # Elapsed: the next call is admitted as a HALF_OPEN probe.
    clock.advance(1)
    observed: list[CircuitState] = []

    async def _probe() -> str:
        observed.append(breaker.current_state)
        return "ok"

    result = await breaker.call(_probe)

    assert observed == [CircuitState.HALF_OPEN]  # transitioned to half-open
    assert result == "ok"
    assert breaker.current_state is CircuitState.CLOSED  # success closed it
    assert breaker.failure_count == 0


# --------------------------------------------------------------------------- #
# 5. Failed probe reopens the circuit
# --------------------------------------------------------------------------- #
async def test_failed_probe_reopens_circuit() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(
        failure_threshold=1, recovery_timeout_seconds=10, time_source=clock
    )

    with pytest.raises(RuntimeError):
        await breaker.call(_boom)
    opened_at_first = clock.now
    assert breaker.current_state is CircuitState.OPEN

    clock.advance(10)  # eligible for a probe
    with pytest.raises(RuntimeError):
        await breaker.call(_boom)  # probe fails

    assert breaker.current_state is CircuitState.OPEN  # reopened
    # The reopen restamped the open time, so a fresh recovery window applies.
    assert clock.now > opened_at_first
    with pytest.raises(CircuitOpenError):
        await breaker.call(_ok)


# --------------------------------------------------------------------------- #
# 8. Metrics are updated correctly (+ reset)
# --------------------------------------------------------------------------- #
async def test_metrics_and_reset() -> None:
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout_seconds=10)

    assert (breaker.success_count, breaker.failure_count) == (0, 0)

    await breaker.call(_ok)
    await breaker.call(_ok)
    assert breaker.success_count == 2
    assert breaker.failure_count == 0

    with pytest.raises(RuntimeError):
        await breaker.call(_boom)
    assert breaker.failure_count == 1
    assert breaker.current_state is CircuitState.CLOSED

    # A success clears the consecutive-failure counter.
    await breaker.call(_ok)
    assert breaker.failure_count == 0
    assert breaker.success_count == 3

    breaker.reset()
    assert breaker.current_state is CircuitState.CLOSED
    assert breaker.success_count == 0
    assert breaker.failure_count == 0


async def test_half_open_admits_only_one_probe() -> None:
    """While half-open, a second concurrent call is rejected as the probe runs."""

    clock = FakeClock()
    breaker = CircuitBreaker(
        failure_threshold=1, recovery_timeout_seconds=10, time_source=clock
    )

    with pytest.raises(RuntimeError):
        await breaker.call(_boom)
    clock.advance(10)

    import asyncio

    release = asyncio.Event()

    async def _slow_probe() -> str:
        await release.wait()
        return "ok"

    probe_task = asyncio.create_task(breaker.call(_slow_probe))
    await asyncio.sleep(0)  # let the probe start and claim the half-open slot

    assert breaker.current_state is CircuitState.HALF_OPEN
    with pytest.raises(CircuitOpenError):
        await breaker.call(_ok)  # second probe blocked

    release.set()
    assert await probe_task == "ok"
    assert breaker.current_state is CircuitState.CLOSED


# --------------------------------------------------------------------------- #
# Provider + service integration
# --------------------------------------------------------------------------- #
class CountingClient:
    """Stand-in OFF client that records calls and returns/raises on demand."""

    def __init__(
        self,
        *,
        error: Exception | None = None,
        images: list[OpenFoodFactsImage] | None = None,
    ) -> None:
        self.calls = 0
        self._error = error
        self._images = images or []

    async def fetch_images_by_barcode(self, barcode: str) -> list[OpenFoodFactsImage]:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return list(self._images)


async def test_provider_raises_circuit_open_error_when_open() -> None:
    """Once open, the provider raises CircuitOpenError without calling the API."""

    client = CountingClient(error=OpenFoodFactsTimeoutError("down"))
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_seconds=60)
    provider = OpenFoodFactsProvider(client=client, circuit_breaker=breaker)

    # First call fails and trips the breaker (one real network attempt).
    with pytest.raises(OpenFoodFactsTimeoutError):
        await provider.search_images(BARCODE)
    assert client.calls == 1
    assert breaker.current_state is CircuitState.OPEN

    # Second call is short-circuited: no further network attempt.
    with pytest.raises(CircuitOpenError):
        await provider.search_images(BARCODE)
    assert client.calls == 1


# --------------------------------------------------------------------------- #
# 6 & 7. Service still returns results (PARTIAL_SUCCESS) when OFF circuit is open
# --------------------------------------------------------------------------- #
async def test_service_partial_success_when_off_circuit_open() -> None:
    client = CountingClient(error=OpenFoodFactsTimeoutError("down"))
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_seconds=60)
    off_provider = OpenFoodFactsProvider(client=client, circuit_breaker=breaker)
    service = ProductImageService(
        registry=ProviderRegistry([off_provider, MockProvider()])
    )

    request = ProductImageSearchRequest(barcode=BARCODE)

    # First search: OFF fails (trips breaker), Mock succeeds -> PARTIAL_SUCCESS.
    first = await service.search(request)
    assert first.status is SearchStatus.PARTIAL_SUCCESS
    assert first.total_images >= 1
    assert client.calls == 1
    assert breaker.current_state is CircuitState.OPEN

    # Second search: OFF is short-circuited but Mock still returns images.
    second = await service.search(request)
    assert second.status is SearchStatus.PARTIAL_SUCCESS
    assert second.total_images >= 1
    # Provider stopped calling the external API while the circuit is open.
    assert client.calls == 1
