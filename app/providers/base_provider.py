"""Provider abstraction.

Defines the contract every image provider must implement. Keeping the surface
this small (a single async method keyed by barcode) makes providers trivially
composable and lets the service treat them uniformly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.product_image import ProductImage


class ImageProvider(ABC):
    """Abstract base class for product-image providers.

    Implementations encapsulate everything source-specific: the client they
    talk to, how raw data maps to :class:`ProductImage`, and how they score
    relevance. The service layer depends only on this interface.

    Error semantics:
        * Return an **empty list** when the provider worked but found no images
          for the barcode (e.g. the product is unknown to that source).
        * **Raise** when the provider itself failed (timeout, transport error,
          malformed upstream response). The service distinguishes these to
          decide between ``FAILED`` and ``PARTIAL_SUCCESS``.
    """

    #: Stable, human-readable identifier used in logs and diagnostics.
    name: str = "provider"

    @abstractmethod
    async def search_images(self, barcode: str) -> list[ProductImage]:
        """Return images for ``barcode`` from this provider's source.

        Args:
            barcode: EAN/UPC barcode to look up.

        Returns:
            A possibly-empty list of :class:`ProductImage` results.

        Raises:
            Exception: Any provider-level failure. The concrete type is
                provider-specific; the service treats every exception as a
                provider failure.
        """

        raise NotImplementedError
