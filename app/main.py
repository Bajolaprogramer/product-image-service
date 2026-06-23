"""Application entrypoint.

Builds and configures the FastAPI application via an ``create_app`` factory so
the app can be constructed cleanly in tests and under different settings. The
factory pattern keeps wiring explicit and dependency-injection friendly.
"""

from fastapi import FastAPI

from app.api.routes import health
from app.core.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure a :class:`FastAPI` instance.

    Args:
        settings: Optional pre-built settings. When omitted, the cached
            application settings are used. Passing settings explicitly is handy
            for tests and alternate deployments.

    Returns:
        A fully wired FastAPI application.
    """

    settings = settings or get_settings()

    app = FastAPI(
        title="Product Image Service",
        version=settings.app_version,
        description=(
            "Microservice for retrieving product images by SKU or barcode "
            "from external providers. (Image retrieval is not yet implemented.)"
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Register routers. New domain routers (e.g. image lookup) get included here.
    app.include_router(health.router)

    return app


# ASGI application instance used by Uvicorn: ``uvicorn app.main:app``.
app = create_app()
