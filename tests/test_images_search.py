"""Tests for the product image search endpoint (POST /api/v1/images/search).

The barcode path now calls Open Food Facts, so endpoint tests that use a barcode
override the service dependency with one backed by a mocked HTTP transport — no
real network calls are made. SKU-only searches still use built-in mock data.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.clients.open_food_facts_client import OpenFoodFactsClient
from app.main import create_app
from app.models.product_image import ImageSource, SearchStatus
from app.services.product_image_service import (
    ProductImageService,
    get_product_image_service,
)

SEARCH_URL = "/api/v1/images/search"
BARCODE = "3017620422003"

PRODUCT_FOUND_BODY = {
    "status": 1,
    "product": {
        "image_front_url": "https://images.openfoodfacts.org/3017620422003/front.jpg",
        "image_ingredients_url": "https://images.openfoodfacts.org/3017620422003/ing.jpg",
    },
}


def _service_with_mocked_off(body: dict, status_code: int = 200) -> ProductImageService:
    """Build a service whose Open Food Facts client returns a canned response."""

    transport = httpx.MockTransport(lambda _req: httpx.Response(status_code, json=body))
    http_client = httpx.AsyncClient(transport=transport, base_url="https://test")
    off_client = OpenFoodFactsClient(base_url="https://test", http_client=http_client)
    return ProductImageService(open_food_facts_client=off_client)


@pytest.fixture
def barcode_client() -> Iterator[TestClient]:
    """A ``TestClient`` whose service resolves barcodes from a mocked provider."""

    app = create_app()
    app.dependency_overrides[get_product_image_service] = (
        lambda: _service_with_mocked_off(PRODUCT_FOUND_BODY)
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_search_by_barcode(barcode_client: TestClient) -> None:
    """A barcode search succeeds and returns Open Food Facts images."""

    response = barcode_client.post(SEARCH_URL, json={"barcode": BARCODE})

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == BARCODE
    assert body["status"] == SearchStatus.SUCCESS.value
    assert len(body["images"]) >= 2
    assert all(img["source"] == ImageSource.OPEN_FOOD_FACTS.value for img in body["images"])


def test_search_by_sku(client: TestClient) -> None:
    """A search keyed by SKU succeeds using mock data and echoes the SKU."""

    response = client.post(SEARCH_URL, json={"sku": "SKU-12345"})

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "SKU-12345"
    assert body["status"] == SearchStatus.SUCCESS.value
    assert len(body["images"]) >= 2


def test_search_empty_request_is_rejected(client: TestClient) -> None:
    """A request with neither barcode nor sku fails validation (HTTP 422)."""

    response = client.post(SEARCH_URL, json={})

    assert response.status_code == 422


def test_search_blank_values_are_rejected(client: TestClient) -> None:
    """Whitespace-only identifiers do not count as provided."""

    response = client.post(SEARCH_URL, json={"barcode": "  ", "sku": ""})

    assert response.status_code == 422


def test_response_schema_correctness(barcode_client: TestClient) -> None:
    """The response and each image match the documented contract."""

    response = barcode_client.post(SEARCH_URL, json={"barcode": BARCODE})

    assert response.status_code == 200
    body = response.json()

    # Top-level contract.
    assert set(body.keys()) == {"query", "status", "images", "total_images"}
    assert body["status"] in {s.value for s in SearchStatus}
    assert isinstance(body["images"], list)

    # Each image conforms to ProductImage.
    valid_sources = {s.value for s in ImageSource}
    for image in body["images"]:
        assert set(image.keys()) == {
            "image_url",
            "source",
            "relevance_score",
            "width",
            "height",
        }
        assert isinstance(image["image_url"], str)
        assert image["source"] in valid_sources
        assert 0.0 <= image["relevance_score"] <= 1.0


def test_total_images_matches_image_count(client: TestClient) -> None:
    """``total_images`` always equals the length of ``images``."""

    response = client.post(SEARCH_URL, json={"sku": "SKU-12345"})

    assert response.status_code == 200
    body = response.json()
    assert body["total_images"] == len(body["images"])
