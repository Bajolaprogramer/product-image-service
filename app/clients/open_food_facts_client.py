"""Async client for the Open Food Facts product database.

This module is the **only** place that knows how to speak HTTP to Open Food
Facts. It queries a product by barcode, parses the JSON response, and returns a
list of normalized images (:class:`OpenFoodFactsImage`). Domain concepts such as
``ProductImage`` / ``ImageSource`` deliberately live in the service layer — the
client stays a thin, provider-specific adapter.

Failure modes are surfaced as a small typed exception hierarchy
(:class:`OpenFoodFactsError` and subclasses) so the service layer can translate
them into a response without ever inspecting HTTP details or crashing.
"""

from __future__ import annotations

import httpx
from pydantic import BaseModel, Field

#: Default public API root. Overridable via settings for tests/self-hosting.
DEFAULT_BASE_URL = "https://world.openfoodfacts.org"

#: Product fields requested from Open Food Facts to keep payloads small. The
#: parser is generic (any ``image*_url`` field), but narrowing the response is
#: good API citizenship.
_PRODUCT_FIELDS = (
    "image_url,image_front_url,image_front_small_url,"
    "image_ingredients_url,image_nutrition_url,image_packaging_url"
)


class OpenFoodFactsError(Exception):
    """Base class for all Open Food Facts client failures."""


class ProductNotFoundError(OpenFoodFactsError):
    """Raised when the requested barcode does not resolve to a product."""

    def __init__(self, barcode: str) -> None:
        super().__init__(f"No Open Food Facts product found for barcode {barcode!r}.")
        self.barcode = barcode


class OpenFoodFactsTimeoutError(OpenFoodFactsError):
    """Raised when the request to Open Food Facts times out."""


class OpenFoodFactsResponseError(OpenFoodFactsError):
    """Raised when the response is unreachable, non-2xx, or malformed."""


class OpenFoodFactsImage(BaseModel):
    """A normalized image extracted from an Open Food Facts product.

    Provider-neutral on purpose: it carries only the URL and (when available)
    pixel dimensions. The service layer enriches this into a domain
    ``ProductImage`` with source and relevance metadata.
    """

    url: str = Field(..., description="Absolute URL of the product image.")
    width: int | None = Field(default=None, description="Image width in pixels.")
    height: int | None = Field(default=None, description="Image height in pixels.")


class OpenFoodFactsClient:
    """Async adapter over the Open Food Facts product API.

    The client is dependency-injection friendly: a pre-built
    :class:`httpx.AsyncClient` may be supplied (handy for tests via
    ``httpx.MockTransport``); otherwise a short-lived client is created per
    request using the configured timeout.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 10.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """Configure the client.

        Args:
            base_url: Root URL of the Open Food Facts API.
            timeout: Per-request timeout in seconds (used only when no
                ``http_client`` is injected).
            http_client: Optional shared/async HTTP client. When provided it is
                used as-is and its lifecycle is owned by the caller.
        """

        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._http_client = http_client

    async def fetch_images_by_barcode(self, barcode: str) -> list[OpenFoodFactsImage]:
        """Fetch normalized images for a product identified by ``barcode``.

        Args:
            barcode: EAN/UPC barcode to look up.

        Returns:
            A (possibly empty) list of normalized images. An empty list means
            the product exists but exposes no images.

        Raises:
            ProductNotFoundError: The barcode does not match any product.
            OpenFoodFactsTimeoutError: The request timed out.
            OpenFoodFactsResponseError: The response was unreachable, non-2xx,
                or could not be parsed.
        """

        url = f"{self._base_url}/api/v2/product/{barcode}.json"
        params = {"fields": _PRODUCT_FIELDS}
        response = await self._get(url, params=params)

        if response.status_code == 404:
            raise ProductNotFoundError(barcode)
        if response.status_code >= 400:
            raise OpenFoodFactsResponseError(
                f"Open Food Facts returned HTTP {response.status_code} "
                f"for barcode {barcode!r}."
            )

        data = self._parse_json(response)

        # Open Food Facts signals "not found" with status == 0 (HTTP 200).
        if data.get("status") == 0:
            raise ProductNotFoundError(barcode)

        product = data.get("product")
        if not isinstance(product, dict):
            raise OpenFoodFactsResponseError(
                f"Open Food Facts response for barcode {barcode!r} is missing a "
                "valid 'product' object."
            )

        return self._extract_images(product)

    async def _get(
        self, url: str, params: dict[str, str]
    ) -> httpx.Response:
        """Perform the GET request, normalizing transport errors.

        Uses the injected client when present, otherwise opens a short-lived one.
        """

        try:
            if self._http_client is not None:
                return await self._http_client.get(url, params=params)
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                return await client.get(url, params=params)
        except httpx.TimeoutException as exc:
            raise OpenFoodFactsTimeoutError(
                f"Request to {url} timed out after {self._timeout}s."
            ) from exc
        except httpx.HTTPError as exc:
            raise OpenFoodFactsResponseError(
                f"HTTP error contacting Open Food Facts: {exc}"
            ) from exc

    @staticmethod
    def _parse_json(response: httpx.Response) -> dict:
        """Decode the response body as a JSON object.

        Raises:
            OpenFoodFactsResponseError: The body is not valid JSON or not an
                object.
        """

        try:
            data = response.json()
        except ValueError as exc:  # includes json.JSONDecodeError
            raise OpenFoodFactsResponseError(
                "Open Food Facts response was not valid JSON."
            ) from exc

        if not isinstance(data, dict):
            raise OpenFoodFactsResponseError(
                "Open Food Facts response was not a JSON object."
            )
        return data

    @staticmethod
    def _extract_images(product: dict) -> list[OpenFoodFactsImage]:
        """Extract de-duplicated image URLs from a product object.

        Picks up any top-level ``image*_url`` string field (e.g.
        ``image_front_url``, ``image_url``). This is resilient to the provider
        adding new image variants and tolerant of missing fields.
        """

        images: list[OpenFoodFactsImage] = []
        seen: set[str] = set()

        for key, value in product.items():
            if (
                isinstance(key, str)
                and key.startswith("image")
                and key.endswith("_url")
                and isinstance(value, str)
                and value
                and value not in seen
            ):
                seen.add(value)
                images.append(OpenFoodFactsImage(url=value))

        return images
