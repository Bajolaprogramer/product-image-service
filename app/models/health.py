"""Response models for health/readiness endpoints."""

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Schema returned by the ``GET /health`` endpoint."""

    status: str = Field(..., description="Overall service health indicator.")
    service: str = Field(..., description="Logical name of this service.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "healthy",
                "service": "product-image-service",
            }
        }
    }
