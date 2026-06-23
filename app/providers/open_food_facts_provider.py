"""Open Food Facts image provider.

Wraps the (HTTP-only) :class:`OpenFoodFactsClient` and adapts its normalized
images into domain :class:`ProductImage` models. All Open Food Facts specifics —
client wiring, relevance scoring, and "product not found" handling — live here,
keeping the service layer provider-agnostic.
"""

from __future__ import annotations

from app.clients.open_food_facts_client import (
    OpenFoodFactsClient,
    ProductNotFoundError,
)
from app.models.product_image import ImageSource, ProductImage
from app.providers.base_provider import ImageProvider


class OpenFoodFactsProvider(ImageProvider):
    """Provider backed by the Open Food Facts product database."""

    name = "open_food_facts"

    def __init__(self, client: OpenFoodFactsClient | None = None) -> None:
        """Wire the provider with its HTTP client.

        Args:
            client: Pre-configured Open Food Facts client. Defaults to one
                targeting the public API; inject a configured or fake client for
                production settings and tests.
        """

        self._client = client or OpenFoodFactsClient()

    async def search_images(self, barcode: str) -> list[ProductImage]:
        """Return Open Food Facts images for ``barcode``.

        A "product not found" result is a successful query with no images, so it
        returns an empty list. Genuine failures (timeout, malformed response,
        non-2xx) propagate from the client and are treated as a provider failure
        by the service.
        """

        try:
            raw_images = await self._client.fetch_images_by_barcode(barcode)
        except ProductNotFoundError:
            return []

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
