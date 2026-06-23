"""Tests for the Open Food Facts HTTP client.

HTTP is faked with ``httpx.MockTransport`` so the real request building, status
handling, and JSON parsing run without network access. Provider-level mapping
and service aggregation are covered in ``test_providers.py``.
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

BARCODE = "3017620422003"

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


def _client_with(
    handler: Callable[[httpx.Request], httpx.Response],
) -> OpenFoodFactsClient:
    """Build an ``OpenFoodFactsClient`` whose HTTP is driven by ``handler``."""

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport, base_url="https://test")
    return OpenFoodFactsClient(base_url="https://test", http_client=http_client)


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
