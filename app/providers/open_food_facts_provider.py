"""Open Food Facts image provider.

Wraps the (HTTP-only) :class:`OpenFoodFactsClient` and adapts its normalized
images into domain :class:`ProductImage` models. All Open Food Facts specifics —
client wiring, relevance scoring, "product not found" handling, and resilience —
live here, keeping the service layer provider-agnostic.

Resilience: outbound calls are guarded by a :class:`CircuitBreaker`. After
repeated client failures the circuit opens and ``search_images`` raises
:class:`CircuitOpenError` without touching the network, letting the service skip
this provider and degrade gracefully.
"""

from __future__ import annotations

from app.clients.open_food_facts_client import (
    OpenFoodFactsClient,
    OpenFoodFactsImage,
    ProductNotFoundError,
)
from app.models.product_image import ImageSource, ProductImage
from app.providers.base_provider import ImageProvider
from app.resilience.circuit_breaker import CircuitBreaker

#: Conservative defaults used when no breaker is injected.
_DEFAULT_FAILURE_THRESHOLD = 5
_DEFAULT_RECOVERY_TIMEOUT_SECONDS = 30.0


class OpenFoodFactsProvider(ImageProvider):
    """Provider backed by the Open Food Facts product database."""

    name = "open_food_facts"

    def __init__(
        self,
        client: OpenFoodFactsClient | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        """Wire the provider with its HTTP client and circuit breaker.

        Args:
            client: Pre-configured Open Food Facts client. Defaults to one
                targeting the public API; inject a configured or fake client for
                production settings and tests.
            circuit_breaker: Breaker guarding outbound calls. Defaults to a
                conservatively configured breaker; inject one to share state or
                control thresholds (e.g. in tests).
        """

        self._client = client or OpenFoodFactsClient()
        self._breaker = circuit_breaker or CircuitBreaker(
            failure_threshold=_DEFAULT_FAILURE_THRESHOLD,
            recovery_timeout_seconds=_DEFAULT_RECOVERY_TIMEOUT_SECONDS,
        )

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        """The breaker guarding this provider (exposed for metrics/inspection)."""

        return self._breaker

    async def search_images(self, barcode: str) -> list[ProductImage]:
        """Return Open Food Facts images for ``barcode``.

        The client call is executed through the circuit breaker. A "product not
        found" result is a successful query with no images (it does **not**
        count as a breaker failure), so it returns an empty list. Genuine
        failures (timeout, malformed response, non-2xx) propagate from the
        client and are recorded by the breaker.

        Raises:
            CircuitOpenError: The breaker is open; no network call is made.
        """

        raw_images = await self._breaker.call(self._fetch_images, barcode)

        return [
            ProductImage(
                image_url=image.url,
                source=ImageSource.OPEN_FOOD_FACTS,
                # Providers tend to return the most representative image (the
                # product front) first, so earlier images score higher.
                relevance_score=max(0.1, round(1.0 - index * 0.1, 2)),
                width=image.width,
                height=image.height,
            )
            for index, image in enumerate(raw_images)
        ]

    async def _fetch_images(self, barcode: str) -> list[OpenFoodFactsImage]:
        """Fetch raw images, treating "not found" as an empty success.

        Catching :class:`ProductNotFoundError` here — *inside* the operation the
        breaker wraps — ensures a missing product is recorded as a success, so a
        catalogue of unknown barcodes never trips the circuit.
        """

        try:
            return await self._client.fetch_images_by_barcode(barcode)
        except ProductNotFoundError:
            return []
