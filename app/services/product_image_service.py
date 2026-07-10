"""Business logic for product image retrieval.

The :class:`ProductImageService` orchestrates a search: it selects an identifier,
delegates provider communication to clients, converts normalized provider data
into domain :class:`ProductImage` models, and shapes the response.

Provider integration status:

* **barcode** — backed by the real :class:`OpenFoodFactsClient`.
* **sku** — still returns mock data until a SKU-capable provider is added.

The service contains **no** raw HTTP logic; all network access lives in the
clients layer. Provider failures are caught here and translated into a graceful
``FAILED`` response so the API never crashes.
"""

from __future__ import annotations

from app.clients.open_food_facts_client import (
    OpenFoodFactsClient,
    OpenFoodFactsError,
    OpenFoodFactsImage,
    ProductNotFoundError,
)
from app.models.product_image import (
    ImageSource,
    ProductImage,
    ProductImageSearchRequest,
    ProductImageSearchResponse,
    SearchStatus,
)


class ProductImageService:
    """Coordinates product image searches across providers.

    The service is async-ready and stateless aside from its injected clients,
    so it can be constructed per-request and injected into routes via FastAPI's
    dependency system. Injecting the client keeps the service unit-testable
    without real network access.
    """

    def __init__(self, open_food_facts_client: OpenFoodFactsClient | None = None) -> None:
        """Wire the service with its provider clients.

        Args:
            open_food_facts_client: Client used for barcode lookups. Defaults to
                a client targeting the public API; inject a configured or fake
                client for production settings and tests.
        """

        self._off_client = open_food_facts_client or OpenFoodFactsClient()

    async def search(
        self, request: ProductImageSearchRequest
    ) -> ProductImageSearchResponse:
        """Search for product images matching the given identifiers.

        Barcode lookups take precedence and hit the real provider; SKU-only
        requests fall back to mock data for now.

        Args:
            request: Validated search request containing a barcode and/or SKU.

        Returns:
            A populated :class:`ProductImageSearchResponse`.
        """

        if request.barcode and request.barcode.strip():
            return await self._search_by_barcode(request.barcode.strip())

        # Request validation guarantees a SKU is present when barcode is absent.
        assert request.sku is not None
        return await self._search_by_sku(request.sku.strip())

    async def _search_by_barcode(self, barcode: str) -> ProductImageSearchResponse:
        """Look up images for a barcode via Open Food Facts.

        Any provider failure (not found, timeout, malformed response) is caught
        and reported as an empty ``FAILED`` result — the endpoint never raises.
        """

        try:
            raw_images = await self._off_client.fetch_images_by_barcode(barcode)
        except ProductNotFoundError:
            raw_images = []
        except OpenFoodFactsError:
            # Timeouts, connection errors, malformed responses, non-2xx, etc.
            raw_images = []

        images = self._to_product_images(raw_images)
        return ProductImageSearchResponse(
            query=barcode,
            status=SearchStatus.SUCCESS if images else SearchStatus.FAILED,
            images=images,
            total_images=len(images),
        )

    async def _search_by_sku(self, sku: str) -> ProductImageSearchResponse:
        """Return mock images for a SKU.

        Placeholder until a SKU-capable provider client is introduced; the async
        signature means that swap will not change callers.
        """

        images = self._mock_images(sku)
        return ProductImageSearchResponse(
            query=sku,
            status=SearchStatus.SUCCESS if images else SearchStatus.FAILED,
            images=images,
            total_images=len(images),
        )

    @staticmethod
    def _to_product_images(
        raw_images: list[OpenFoodFactsImage],
    ) -> list[ProductImage]:
        """Convert normalized provider images into domain models.

        Relevance is approximated by position: providers tend to return the most
        representative image (the product front) first, so earlier images score
        higher. This keeps the contract meaningful until real ranking exists.
        """

        product_images: list[ProductImage] = []
        for index, image in enumerate(raw_images):
            product_images.append(
                ProductImage(
                    image_url=image.url,
                    source=ImageSource.OPEN_FOOD_FACTS,
                    relevance_score=max(0.1, round(1.0 - index * 0.1, 2)),
                    width=image.width,
                    height=image.height,
                )
            )
        return product_images

    @staticmethod
    def _mock_images(query: str) -> list[ProductImage]:
        """Return realistic mock images for a SKU query."""

        return [
            ProductImage(
                image_url=f"https://images.example.com/{query}/front.jpg",
                source=ImageSource.UPC_DATABASE,
                relevance_score=0.95,
                width=800,
                height=800,
            ),
            ProductImage(
                image_url=f"https://images.example.com/{query}/back.jpg",
                source=ImageSource.UPC_DATABASE,
                relevance_score=0.82,
                width=600,
                height=600,
            ),
        ]


def get_product_image_service() -> ProductImageService:
    """Provide a :class:`ProductImageService` instance.

    Used as a FastAPI dependency so routes stay decoupled from construction and
    tests can override it via ``app.dependency_overrides``. The Open Food Facts
    client is configured from application settings.
    """

    from app.core.config import get_settings

    settings = get_settings()
    off_client = OpenFoodFactsClient(
        base_url=settings.open_food_facts_base_url,
        timeout=settings.external_api_timeout_seconds,
    )
    return ProductImageService(open_food_facts_client=off_client)
