"""Health-check route.

Exposes a lightweight, dependency-free endpoint used by load balancers,
orchestrators (Kubernetes liveness/readiness probes) and uptime monitors to
confirm the service is running.
"""

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.models.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health check",
    status_code=200,
)
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Return the current health status of the service.

    The service name is sourced from configuration so the response stays
    consistent across environments.
    """

    return HealthResponse(status="healthy", service=settings.service_name)
