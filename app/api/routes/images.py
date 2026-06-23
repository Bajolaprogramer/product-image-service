"""Product image search routes (API v1)."""

from fastapi import APIRouter, Depends

from app.models.product_image import (
    ProductImageSearchRequest,
    ProductImageSearchResponse,
)
from app.services.product_image_service import (
    ProductImageService,
    get_product_image_service,
)

router = APIRouter(prefix="/api/v1/images", tags=["images"])


@router.post(
    "/search",
    response_model=ProductImageSearchResponse,
    summary="Search product images by SKU or barcode",
    status_code=200,
)
async def search_images(
    request: ProductImageSearchRequest,
    service: ProductImageService = Depends(get_product_image_service),
) -> ProductImageSearchResponse:
    """Search for product images.

    The route is a thin adapter: it validates the request (via the request
    model), delegates all business logic to :class:`ProductImageService`, and
    returns the service's response. Provider integration lives behind the
    service, so this handler stays unchanged as the backend grows.
    """

    return await service.search(request)
