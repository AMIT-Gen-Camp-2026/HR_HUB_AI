"""Build the provider named in settings. The only place that knows all four exist."""
from __future__ import annotations

import logging

from app.providers.base import ProviderAdapter
from config.settings import Settings

log = logging.getLogger("app.providers")


def build_provider(settings: Settings) -> ProviderAdapter:
    name = settings.provider

    if name == "stub":
        from app.providers.stub_provider import StubProvider

        return StubProvider()

    if name == "api":
        from app.providers.api_provider import ApiProvider

        if not settings.api_key:
            raise RuntimeError(
                "PROVIDER=api but API_KEY is empty. Set it in .env, or run with PROVIDER=stub."
            )
        return ApiProvider(settings)

    if name == "hf":
        from app.providers.hf_provider import HuggingFaceProvider

        return HuggingFaceProvider(settings)

    if name == "local":
        from app.providers.local_provider import LocalProvider

        return LocalProvider(settings)

    raise ValueError(f"Unknown PROVIDER={name!r}. Use one of: api, hf, local, stub.")
