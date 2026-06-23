"""Tests for the provider layer and multi-provider aggregation.

Covers the concrete providers (Open Food Facts, mock) and the service's
fan-out/merge/rank/status logic using lightweight stub providers.
"""

from __future__ import annotations

import httpx
import pytest

from app.clients.open_food_facts_client import OpenFoodFactsClient
from app.models.product_image import (
    ImageSource,
    ProductImage,
    ProductImageSearchRequest,
    SearchStatus,
)
from app.providers.base_provider import ImageProvider
from app.providers.mock_provider import MockProvider
from app.providers.open_food_facts_provider import OpenFoodFactsProvider
from app.providers.registry import ProviderRegistry
from app.services.product_image_service import ProductImageService

BARCODE = "3017620422003"

OFF_FOUND_BODY = {
    "status": 1,
    "product": {
        "image_front_url": "https://off.example.com/front.jpg",
        "image_ingredients_url": "https://off.example.com/ing.jpg",
    },
}
OFF_NOT_FOUND_BODY = {"status": 0}


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
class StubProvider(ImageProvider):
    """A provider that returns canned images or raises a canned error."""

    def __init__(
        self,
        *,
        name: str,
        images: list[ProductImage] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.name = name
        self._images = images or []
        self._error = error

    async def search_images(self, barcode: str) -> list[ProductImage]:
        if self._error is not None:
            raise self._error
        return list(self._images)


def _img(url: str, score: float, source: ImageSource = ImageSource.UNKNOWN) -> ProductImage:
    return ProductImage(image_url=url, source=source, relevance_score=score)


def _service(*providers: ImageProvider) -> ProductImageService:
    return ProductImageService(registry=ProviderRegistry(list(providers)))


async def _search(service: ProductImageService, barcode: str = BARCODE):
    return await service.search(ProductImageSearchRequest(barcode=barcode))


def _off_provider_with(body: dict, status_code: int = 200) -> OpenFoodFactsProvider:
    transport = httpx.MockTransport(lambda _req: httpx.Response(status_code, json=body))
    http_client = httpx.AsyncClient(transport=transport, base_url="https://test")
    return OpenFoodFactsProvider(
        client=OpenFoodFactsClient(base_url="https://test", http_client=http_client)
    )


# --------------------------------------------------------------------------- #
# Concrete providers
# --------------------------------------------------------------------------- #
async def test_open_food_facts_provider_maps_domain_models() -> None:
    """The OFF provider maps client output to OFF-sourced ProductImages."""

    provider = _off_provider_with(OFF_FOUND_BODY)

    images = await provider.search_images(BARCODE)

    assert [i.image_url for i in images] == [
        "https://off.example.com/front.jpg",
        "https://off.example.com/ing.jpg",
    ]
    assert all(i.source == ImageSource.OPEN_FOOD_FACTS for i in images)
    assert images[0].relevance_score == 1.0
    assert images[1].relevance_score < images[0].relevance_score


async def test_open_food_facts_provider_not_found_returns_empty() -> None:
    """Product-not-found is a successful empty result, not a failure."""

    provider = _off_provider_with(OFF_NOT_FOUND_BODY)

    assert await provider.search_images(BARCODE) == []


async def test_mock_provider_returns_realistic_images() -> None:
    """The mock provider returns UPC-database-sourced images for any barcode."""

    images = await MockProvider().search_images(BARCODE)

    assert len(images) >= 1
    assert all(i.source == ImageSource.UPC_DATABASE for i in images)
    assert all(BARCODE in i.image_url for i in images)


# --------------------------------------------------------------------------- #
# Aggregation in the service
# --------------------------------------------------------------------------- #
async def test_aggregates_across_providers() -> None:
    """Images from all providers are merged into one response."""

    service = _service(
        StubProvider(name="a", images=[_img("https://a/1.jpg", 0.8)]),
        StubProvider(name="b", images=[_img("https://b/1.jpg", 0.6)]),
    )

    response = await _search(service)

    assert response.status == SearchStatus.SUCCESS
    assert {i.image_url for i in response.images} == {"https://a/1.jpg", "https://b/1.jpg"}
    assert response.total_images == 2


async def test_duplicate_urls_are_removed_keeping_highest_score() -> None:
    """A URL reported by two providers appears once, with the higher score."""

    service = _service(
        StubProvider(name="a", images=[_img("https://dup/1.jpg", 0.5)]),
        StubProvider(name="b", images=[_img("https://dup/1.jpg", 0.9)]),
    )

    response = await _search(service)

    assert response.total_images == 1
    assert response.images[0].image_url == "https://dup/1.jpg"
    assert response.images[0].relevance_score == 0.9


async def test_results_sorted_by_relevance_descending() -> None:
    """Merged images are ordered by relevance, highest first."""

    service = _service(
        StubProvider(name="a", images=[_img("https://a/low.jpg", 0.2), _img("https://a/high.jpg", 0.95)]),
        StubProvider(name="b", images=[_img("https://b/mid.jpg", 0.6)]),
    )

    response = await _search(service)

    scores = [i.relevance_score for i in response.images]
    assert scores == sorted(scores, reverse=True)
    assert response.images[0].image_url == "https://a/high.jpg"


async def test_partial_success_when_one_provider_fails() -> None:
    """One provider failing while another returns images -> PARTIAL_SUCCESS."""

    service = _service(
        StubProvider(name="ok", images=[_img("https://ok/1.jpg", 0.8)]),
        StubProvider(name="boom", error=RuntimeError("provider down")),
    )

    response = await _search(service)

    assert response.status == SearchStatus.PARTIAL_SUCCESS
    assert response.total_images == 1


async def test_success_when_all_providers_succeed() -> None:
    """No failures and images present -> SUCCESS."""

    service = _service(
        StubProvider(name="a", images=[_img("https://a/1.jpg", 0.8)]),
        StubProvider(name="b", images=[]),
    )

    response = await _search(service)

    assert response.status == SearchStatus.SUCCESS


async def test_failed_when_all_providers_fail() -> None:
    """Every provider failing -> FAILED with no images."""

    service = _service(
        StubProvider(name="a", error=TimeoutError()),
        StubProvider(name="b", error=RuntimeError()),
    )

    response = await _search(service)

    assert response.status == SearchStatus.FAILED
    assert response.images == []


async def test_failed_when_no_images_found() -> None:
    """Providers succeed but return nothing -> FAILED."""

    service = _service(
        StubProvider(name="a", images=[]),
        StubProvider(name="b", images=[]),
    )

    response = await _search(service)

    assert response.status == SearchStatus.FAILED
    assert response.total_images == 0


async def test_providers_are_queried_concurrently() -> None:
    """Two slow providers complete in roughly one provider's duration."""

    import asyncio

    class SlowProvider(ImageProvider):
        name = "slow"

        def __init__(self, url: str) -> None:
            self._url = url

        async def search_images(self, barcode: str) -> list[ProductImage]:
            await asyncio.sleep(0.1)
            return [_img(self._url, 0.5)]

    service = _service(SlowProvider("https://s/1.jpg"), SlowProvider("https://s/2.jpg"))

    loop = asyncio.get_running_loop()
    start = loop.time()
    response = await _search(service)
    elapsed = loop.time() - start

    assert response.total_images == 2
    # Concurrent: ~0.1s total, not ~0.2s. Generous bound to avoid flakiness.
    assert elapsed < 0.18
