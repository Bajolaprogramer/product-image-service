"""Tests for the product image search endpoint (POST /api/v1/images/search)."""

from fastapi.testclient import TestClient

from app.models.product_image import ImageSource, SearchStatus

SEARCH_URL = "/api/v1/images/search"


def test_search_by_barcode(client: TestClient) -> None:
    """A search keyed by barcode succeeds and echoes the barcode as the query."""

    response = client.post(SEARCH_URL, json={"barcode": "3017620422003"})

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "3017620422003"
    assert body["status"] == SearchStatus.SUCCESS.value
    assert len(body["images"]) >= 2


def test_search_by_sku(client: TestClient) -> None:
    """A search keyed by SKU succeeds and echoes the SKU as the query."""

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


def test_response_schema_correctness(client: TestClient) -> None:
    """The response and each image match the documented contract."""

    response = client.post(SEARCH_URL, json={"barcode": "3017620422003"})

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
