"""Business logic for product image retrieval.

The :class:`ProductImageService` owns the orchestration of a search: choosing an
identifier, querying providers, scoring/merging results, and shaping the
response. External provider integration is intentionally **not** implemented
yet — the service currently returns realistic mock data while exposing the exact
seam where real provider clients will plug in.
"""

from __future__ import annotations

from app.models.product_image import (
    ImageSource,
    ProductImage,
    ProductImageSearchRequest,
    ProductImageSearchResponse,
    SearchStatus,
)


class ProductImageService:
    """Coordinates product image searches.

    The service is stateless and async-ready so it can later ``await`` external
    provider clients without changing its public surface. It is designed to be
    constructed per-request (or shared) and injected into routes via FastAPI's
    dependency system, which keeps it easily testable and mockable.
    """

    async def search(
        self, request: ProductImageSearchRequest
    ) -> ProductImageSearchResponse:
        """Search for product images matching the given identifiers.

        Args:
            request: Validated search request containing a barcode and/or SKU.

        Returns:
            A populated :class:`ProductImageSearchResponse`. Currently backed by
            mock data; the control flow mirrors what real provider fan-out will
            look like.
        """

        query = self._resolve_query(request)
        images = await self._fetch_mock_images(query)

        return ProductImageSearchResponse(
            query=query,
            status=SearchStatus.SUCCESS if images else SearchStatus.FAILED,
            images=images,
            total_images=len(images),
        )

    @staticmethod
    def _resolve_query(request: ProductImageSearchRequest) -> str:
        """Pick the identifier to search with.

        Barcode is preferred over SKU because providers key on it more reliably.
        The request validator guarantees at least one is present.
        """

        identifier = request.barcode or request.sku
        assert identifier is not None  # guaranteed by request validation
        return identifier

    async def _fetch_mock_images(self, query: str) -> list[ProductImage]:
        """Return realistic mock images for ``query``.

        Replace this with provider client calls (e.g. Open Food Facts, a UPC
        database) once external integration begins. Keeping the signature async
        means that swap requires no caller changes.
        """

        return [
            ProductImage(
                image_url=f"https://images.example.com/{query}/front.jpg",
                source=ImageSource.OPEN_FOOD_FACTS,
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
    tests can override it via ``app.dependency_overrides``.
    """

    return ProductImageService()
