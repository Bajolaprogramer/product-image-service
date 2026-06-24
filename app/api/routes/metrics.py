"""Prometheus scrape endpoint.

Serializes the default ``prometheus_client`` registry in the Prometheus text
exposition format. Excluded from the OpenAPI schema since it is an operational
endpoint, not part of the public API.
"""

from fastapi import APIRouter
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter()


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Return all registered metrics in Prometheus text format."""

    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
