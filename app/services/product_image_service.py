"""Business logic for product image retrieval.

The :class:`ProductImageService` aggregates results across multiple providers.
For a barcode it queries every active provider concurrently, merges their
images, removes duplicate URLs (keeping the highest-scoring instance), and ranks
the result by relevance. SKU lookups still use mock data until a SKU-capable
provider exists.

The service holds **no** HTTP or provider-specific logic — providers (and the
clients beneath them) own that. Provider failures are tolerated: the service
degrades to ``PARTIAL_SUCCESS`` or ``FAILED`` rather than raising, so the API
never crashes.
"""

from __future__ import annotations

import asyncio

from app.models.product_image import (
    ImageSource,
    ProductImage,
    ProductImageSearchRequest,
    ProductImageSearchResponse,
    SearchStatus,
)
from app.observability import metrics
from app.providers.registry import ProviderRegistry
from app.resilience.circuit_breaker import CircuitOpenError


class ProductImageService:
    """Coordinates multi-provider product image searches.

    The service is async-first and depends only on a :class:`ProviderRegistry`,
    so it is easy to construct with real or fake providers and to inject into
    routes via FastAPI's dependency system.
    """

    def __init__(self, registry: ProviderRegistry | None = None) -> None:
        """Wire the service with its provider registry.

        Args:
            registry: Source of active providers. Defaults to an empty registry
                (useful in isolation); production wiring supplies a populated
                one via :func:`get_product_image_service`.
        """

        self._registry = registry or ProviderRegistry()

    async def search(
        self, request: ProductImageSearchRequest
    ) -> ProductImageSearchResponse:
        """Search for product images matching the given identifiers.

        Barcode lookups fan out across all providers; SKU-only requests fall
        back to mock data for now.

        Args:
            request: Validated search request containing a barcode and/or SKU.

        Returns:
            A populated :class:`ProductImageSearchResponse`.
        """

        metrics.record_search_request()

        if request.barcode and request.barcode.strip():
            response = await self._search_by_barcode(request.barcode.strip())
        else:
            # Request validation guarantees a SKU is present when barcode is absent.
            assert request.sku is not None
            response = await self._search_by_sku(request.sku.strip())

        metrics.record_search_status(response.status)
        return response

    async def _search_by_barcode(self, barcode: str) -> ProductImageSearchResponse:
        """Query all providers concurrently and aggregate their images.

        Status is derived from both the merged image set and whether any
        provider failed:

        * ``SUCCESS`` — images found and every provider succeeded.
        * ``PARTIAL_SUCCESS`` — images found but at least one provider failed.
        * ``FAILED`` — no images found (including the all-providers-failed case).
        """

        providers = self._registry.get_active_providers()

        results = await asyncio.gather(
            *(provider.search_images(barcode) for provider in providers),
            return_exceptions=True,
        )

        collected: list[ProductImage] = []
        had_failure = False
        for provider, result in zip(providers, results):
            if isinstance(result, Exception):
                had_failure = True
                metrics.record_provider_failure(provider.name)
                if isinstance(result, CircuitOpenError):
                    metrics.record_circuit_open(provider.name)
                continue
            collected.extend(result)

        images = self._merge_and_rank(collected)
        status = self._resolve_status(images=images, had_failure=had_failure)

        return ProductImageSearchResponse(
            query=barcode,
            status=status,
            images=images,
            total_images=len(images),
        )

    async def _search_by_sku(self, sku: str) -> ProductImageSearchResponse:
        """Return mock images for a SKU.

        Placeholder until a SKU-capable provider is introduced; the async
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
    def _merge_and_rank(images: list[ProductImage]) -> list[ProductImage]:
        """De-duplicate by URL and sort by relevance descending.

        When the same URL is reported by more than one provider, the
        highest-scoring instance wins. Ties preserve first-seen order (stable
        sort), keeping output deterministic.
        """

        best_by_url: dict[str, ProductImage] = {}
        for image in images:
            existing = best_by_url.get(image.image_url)
            if existing is None or image.relevance_score > existing.relevance_score:
                best_by_url[image.image_url] = image

        return sorted(
            best_by_url.values(),
            key=lambda image: image.relevance_score,
            reverse=True,
        )

    @staticmethod
    def _resolve_status(
        *, images: list[ProductImage], had_failure: bool
    ) -> SearchStatus:
        """Map aggregation outcome to a :class:`SearchStatus`."""

        if not images:
            return SearchStatus.FAILED
        return SearchStatus.PARTIAL_SUCCESS if had_failure else SearchStatus.SUCCESS

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
    """Provide a fully wired :class:`ProductImageService`.

    Builds the active provider set (Open Food Facts + mock second source) from
    application settings. Used as a FastAPI dependency so routes stay decoupled
    from construction and tests can override it via ``app.dependency_overrides``.
    """

    from app.clients.open_food_facts_client import OpenFoodFactsClient
    from app.core.config import get_settings
    from app.providers.mock_provider import MockProvider
    from app.providers.open_food_facts_provider import OpenFoodFactsProvider
    from app.resilience.circuit_breaker import CircuitBreaker

    settings = get_settings()
    off_client = OpenFoodFactsClient(
        base_url=settings.open_food_facts_base_url,
        timeout=settings.external_api_timeout_seconds,
    )
    off_breaker = CircuitBreaker(
        failure_threshold=settings.circuit_breaker_failure_threshold,
        recovery_timeout_seconds=settings.circuit_breaker_recovery_timeout_seconds,
    )
    registry = ProviderRegistry(
        [
            OpenFoodFactsProvider(client=off_client, circuit_breaker=off_breaker),
            MockProvider(),
        ]
    )
    return ProductImageService(registry=registry)
