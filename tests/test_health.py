"""Tests for the health-check endpoint."""

from fastapi.testclient import TestClient


def test_health_returns_200(client: TestClient) -> None:
    """``GET /health`` responds with HTTP 200."""

    response = client.get("/health")
    assert response.status_code == 200


def test_health_payload(client: TestClient) -> None:
    """``GET /health`` returns the expected status and service name."""

    response = client.get("/health")
    assert response.json() == {
        "status": "healthy",
        "service": "product-image-service",
    }
