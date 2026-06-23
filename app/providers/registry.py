"""Provider registry.

A tiny container that holds the set of active providers and hands them to the
service. Centralizing provider membership here means enabling/disabling a
provider — or adding a new one — is a one-line change at composition time and
never touches the service logic.
"""

from __future__ import annotations

from app.providers.base_provider import ImageProvider


class ProviderRegistry:
    """Holds the active image providers for a service instance."""

    def __init__(self, providers: list[ImageProvider] | None = None) -> None:
        """Initialize the registry.

        Args:
            providers: Providers to start with. Order is preserved but not
                semantically significant — results are merged and re-ranked.
        """

        self._providers: list[ImageProvider] = list(providers or [])

    def register(self, provider: ImageProvider) -> None:
        """Add a provider to the registry."""

        self._providers.append(provider)

    def get_active_providers(self) -> list[ImageProvider]:
        """Return all active providers.

        Returns a copy so callers cannot mutate the registry's internal list.
        """

        return list(self._providers)
