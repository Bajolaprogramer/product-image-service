"""Domain models for product image search.

These Pydantic v2 models define the public API contract for retrieving product
images by SKU or barcode. They are deliberately provider-agnostic so that future
external integrations (Open Food Facts, UPC databases, etc.) can populate them
without changing the contract consumers depend on.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class ImageSource(str, Enum):
    """Identifies which provider an image originated from.

    Inherits from ``str`` so values serialize to plain strings in JSON and are
    convenient to compare and log.
    """

    OPEN_FOOD_FACTS = "OPEN_FOOD_FACTS"
    UPC_DATABASE = "UPC_DATABASE"
    UNKNOWN = "UNKNOWN"


class SearchStatus(str, Enum):
    """Outcome of a product image search."""

    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"


class ProductImageSearchRequest(BaseModel):
    """Request payload for a product image search.

    A search is keyed by a product identifier. At least one of ``barcode`` or
    ``sku`` must be supplied; a request with neither is rejected at validation
    time so invalid queries never reach the service layer.
    """

    barcode: str | None = Field(
        default=None,
        description="Product barcode (e.g. EAN/UPC).",
        examples=["3017620422003"],
    )
    sku: str | None = Field(
        default=None,
        description="Stock keeping unit identifying the product.",
        examples=["SKU-12345"],
    )

    @model_validator(mode="after")
    def _require_identifier(self) -> "ProductImageSearchRequest":
        """Ensure at least one identifier is present.

        Raises:
            ValueError: If both ``barcode`` and ``sku`` are missing or blank.
        """

        has_barcode = bool(self.barcode and self.barcode.strip())
        has_sku = bool(self.sku and self.sku.strip())
        if not has_barcode and not has_sku:
            raise ValueError("At least one of 'barcode' or 'sku' must be provided.")
        return self

    model_config = {
        "json_schema_extra": {
            "example": {"barcode": "3017620422003", "sku": "SKU-12345"}
        }
    }


class ProductImage(BaseModel):
    """A single product image returned by a search."""

    image_url: str = Field(..., description="Absolute URL of the product image.")
    source: ImageSource = Field(
        ..., description="Provider the image was sourced from."
    )
    relevance_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence that the image matches the query (0.0–1.0).",
    )
    width: int | None = Field(
        default=None, ge=0, description="Image width in pixels, if known."
    )
    height: int | None = Field(
        default=None, ge=0, description="Image height in pixels, if known."
    )


class ProductImageSearchResponse(BaseModel):
    """Response payload for a product image search."""

    query: str = Field(
        ..., description="The identifier the search was performed with."
    )
    status: SearchStatus = Field(..., description="Outcome of the search.")
    images: list[ProductImage] = Field(
        default_factory=list, description="Matching product images."
    )
    total_images: int = Field(
        ..., ge=0, description="Number of images in this response."
    )
