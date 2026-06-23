"""Mock image provider.

Simulates a second external source (e.g. a UPC image database) so the
aggregation pipeline can be exercised with more than one provider before a real
second integration exists. Returns deterministic, realistic-looking results
derived from the barcode.
"""

from __future__ import annotations

from app.models.product_image import ImageSource, ProductImage
from app.providers.base_provider import ImageProvider


class MockProvider(ImageProvider):
    """Provider returning realistic mock images for any barcode."""

    name = "mock_provider"

    def __init__(self, base_url: str = "https://mock.images.example.com") -> None:
        """Configure the mock provider.

        Args:
            base_url: Root used to build deterministic mock image URLs.
        """

        self._base_url = base_url.rstrip("/")

    async def search_images(self, barcode: str) -> list[ProductImage]:
        """Return a small set of mock images for ``barcode``."""

        return [
            ProductImage(
                image_url=f"{self._base_url}/{barcode}/primary.jpg",
                source=ImageSource.UPC_DATABASE,
                relevance_score=0.90,
                width=1000,
                height=1000,
            ),
            ProductImage(
                image_url=f"{self._base_url}/{barcode}/secondary.jpg",
                source=ImageSource.UPC_DATABASE,
                relevance_score=0.70,
                width=500,
                height=500,
            ),
        ]
