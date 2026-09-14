"""Builds the provider named in settings.provider. This is the ONLY place that
decides which concrete class gets instantiated — app/main.py calls this once at
startup and stores the result on app.extensions['provider']."""
from __future__ import annotations

from app.providers.base import ProviderAdapter
from config.settings import Settings


def build_provider(settings: Settings) -> ProviderAdapter:
    if settings.provider == "api":
        from app.providers.api_provider import GeminiProvider
        return GeminiProvider(settings)
    if settings.provider == "hf":
        from app.providers.hf_provider import HFProvider
        return HFProvider(settings)
    if settings.provider == "local":
        from app.providers.local_provider import LocalProvider
        return LocalProvider(settings)
    if settings.provider == "stub":
        from app.providers.stub_provider import StubProvider
        return StubProvider(settings)
    raise ValueError(f"Unknown provider: {settings.provider!r}")