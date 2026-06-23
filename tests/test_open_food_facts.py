"""Tests for the Open Food Facts client and its service integration.

HTTP is faked with ``httpx.MockTransport`` so the real parsing, error handling,
and service-to-domain mapping run end to end without network access.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from app.clients.open_food_facts_client import (
    OpenFoodFactsClient,
    OpenFoodFactsResponseError,
    OpenFoodFactsTimeoutError,
    ProductNotFoundError,
)
from app.models.product_image import (
    ImageSource,
    ProductImageSearchRequest,
    SearchStatus,
)
from app.services.product_image_service import ProductImageService

BARCODE = "3017620422003"

# A trimmed-but-realistic Open Food Facts "product found" payload.
PRODUCT_FOUND_BODY = {
    "code": BARCODE,
    "status": 1,
    "status_verbose": "product found",
    "product": {
        "image_url": "https://images.openfoodfacts.org/3017620422003/front.400.jpg",
        "image_front_url": "https://images.openfoodfacts.org/3017620422003/front.jpg",
        "image_ingredients_url": "https://images.openfoodfacts.org/3017620422003/ing.jpg",
    },
}

PRODUCT_NOT_FOUND_BODY = {
    "code": BARCODE,
    "status": 0,
    "status_verbose": "product not found",
}

PRODUCT_NO_IMAGES_BODY = {
    "code": BARCODE,
    "status": 1,
    "status_verbose": "product found",
    "product": {"product_name": "Nutella"},
}


def _client_with(handler: Callable[[httpx.Request], httpx.Response]) -> OpenFoodFactsClient:
    """Build an ``OpenFoodFactsClient`` whose HTTP is driven by ``handler``."""

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport, base_url="https://test")
    return OpenFoodFactsClient(base_url="https://test", http_client=http_client)


# --------------------------------------------------------------------------- #
# Client-level tests
# --------------------------------------------------------------------------- #
async def test_client_parses_successful_response() -> None:
    """A 'product found' payload yields de-duplicated normalized images."""

    client = _client_with(lambda _req: httpx.Response(200, json=PRODUCT_FOUND_BODY))

    images = await client.fetch_images_by_barcode(BARCODE)

    urls = [image.url for image in images]
    assert urls == [
        "https://images.openfoodfacts.org/3017620422003/front.400.jpg",
        "https://images.openfoodfacts.org/3017620422003/front.jpg",
        "https://images.openfoodfacts.org/3017620422003/ing.jpg",
    ]


async def test_client_raises_on_status_zero() -> None:
    """``status == 0`` (HTTP 200) is treated as product-not-found."""

    client = _client_with(lambda _req: httpx.Response(200, json=PRODUCT_NOT_FOUND_BODY))

    with pytest.raises(ProductNotFoundError):
        await client.fetch_images_by_barcode(BARCODE)


async def test_client_raises_on_http_404() -> None:
    """A bare HTTP 404 is treated as product-not-found."""

    client = _client_with(lambda _req: httpx.Response(404, json={"status": 0}))

    with pytest.raises(ProductNotFoundError):
        await client.fetch_images_by_barcode(BARCODE)


async def test_client_returns_empty_for_product_without_images() -> None:
    """A found product with no image fields yields an empty list (no error)."""

    client = _client_with(lambda _req: httpx.Response(200, json=PRODUCT_NO_IMAGES_BODY))

    images = await client.fetch_images_by_barcode(BARCODE)

    assert images == []


async def test_client_raises_on_timeout() -> None:
    """Transport timeouts surface as a typed timeout error."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    client = _client_with(handler)

    with pytest.raises(OpenFoodFactsTimeoutError):
        await client.fetch_images_by_barcode(BARCODE)


async def test_client_raises_on_malformed_json() -> None:
    """A non-JSON body surfaces as a typed response error."""

    client = _client_with(lambda _req: httpx.Response(200, content=b"<html>nope</html>"))

    with pytest.raises(OpenFoodFactsResponseError):
        await client.fetch_images_by_barcode(BARCODE)


async def test_client_raises_on_server_error() -> None:
    """A 5xx response surfaces as a typed response error."""

    client = _client_with(lambda _req: httpx.Response(503, text="unavailable"))

    with pytest.raises(OpenFoodFactsResponseError):
        await client.fetch_images_by_barcode(BARCODE)


# --------------------------------------------------------------------------- #
# Service-level integration tests
# --------------------------------------------------------------------------- #
async def test_service_barcode_success_maps_domain_models() -> None:
    """A successful lookup produces SUCCESS with Open Food Facts domain images."""

    service = ProductImageService(
        open_food_facts_client=_client_with(
            lambda _req: httpx.Response(200, json=PRODUCT_FOUND_BODY)
        )
    )

    response = await service.search(ProductImageSearchRequest(barcode=BARCODE))

    assert response.query == BARCODE
    assert response.status == SearchStatus.SUCCESS
    assert response.total_images == len(response.images) == 3
    assert all(img.source == ImageSource.OPEN_FOOD_FACTS for img in response.images)
    # Position-based relevance: first image ranks highest.
    assert response.images[0].relevance_score == 1.0
    assert response.images[1].relevance_score < response.images[0].relevance_score


async def test_service_barcode_not_found_is_failed() -> None:
    """Product-not-found yields a graceful empty FAILED response."""

    service = ProductImageService(
        open_food_facts_client=_client_with(
            lambda _req: httpx.Response(200, json=PRODUCT_NOT_FOUND_BODY)
        )
    )

    response = await service.search(ProductImageSearchRequest(barcode=BARCODE))

    assert response.status == SearchStatus.FAILED
    assert response.images == []
    assert response.total_images == 0


async def test_service_barcode_no_images_is_failed() -> None:
    """A found product with no images yields FAILED (no images located)."""

    service = ProductImageService(
        open_food_facts_client=_client_with(
            lambda _req: httpx.Response(200, json=PRODUCT_NO_IMAGES_BODY)
        )
    )

    response = await service.search(ProductImageSearchRequest(barcode=BARCODE))

    assert response.status == SearchStatus.FAILED
    assert response.total_images == 0


async def test_service_never_crashes_on_client_error() -> None:
    """A provider timeout is swallowed into a FAILED response, not an exception."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    service = ProductImageService(open_food_facts_client=_client_with(handler))

    response = await service.search(ProductImageSearchRequest(barcode=BARCODE))

    assert response.status == SearchStatus.FAILED
    assert response.images == []


async def test_service_sku_still_uses_mock() -> None:
    """SKU-only searches keep returning mock data for now."""

    service = ProductImageService()

    response = await service.search(ProductImageSearchRequest(sku="SKU-12345"))

    assert response.query == "SKU-12345"
    assert response.status == SearchStatus.SUCCESS
    assert len(response.images) >= 2
