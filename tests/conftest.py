"""Shared pytest fixtures."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    """Provide a ``TestClient`` bound to a freshly built application.

    Building the app per test keeps cases isolated and makes dependency
    overrides predictable.
    """

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
