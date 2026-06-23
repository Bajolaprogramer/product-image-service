"""Application configuration.

Settings are loaded from environment variables (and an optional ``.env`` file)
using ``pydantic-settings``. A cached accessor (:func:`get_settings`) is exposed
so the settings object can be used as a FastAPI dependency without re-reading
the environment on every request.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application settings.

    Values are read from the process environment first, then from a ``.env``
    file if present. Unknown environment variables are ignored so the service
    can run alongside other tooling without configuration clashes.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Service metadata ---------------------------------------------------
    service_name: str = "product-image-service"
    app_version: str = "0.1.0"
    environment: str = "development"
    debug: bool = False

    # --- HTTP / server ------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8000

    # --- External providers (reserved for future image-retrieval work) ------
    external_api_base_url: str = ""
    external_api_key: str = ""
    external_api_timeout_seconds: float = 10.0


@lru_cache
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance.

    Caching ensures the environment is parsed once per process. The function is
    dependency-injection friendly: inject it directly (``Depends(get_settings)``)
    and override it in tests via ``app.dependency_overrides``.
    """

    return Settings()
