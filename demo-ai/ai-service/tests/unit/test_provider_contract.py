"""Every provider must satisfy the same contract. Add a provider, add it here."""
from __future__ import annotations

import pytest

from app.providers.base import ProviderAdapter
from app.providers.stub_provider import StubProvider


@pytest.mark.asyncio
async def test_stub_returns_completion() -> None:
    p: ProviderAdapter = StubProvider()
    out = await p.complete("hello")
    assert out.text
    assert out.model_version


@pytest.mark.asyncio
async def test_stub_can_simulate_timeout() -> None:
    from app.errors import ProviderUnavailable

    p = StubProvider(mode="timeout")
    with pytest.raises(ProviderUnavailable):
        await p.complete("hello")


@pytest.mark.asyncio
async def test_stub_can_simulate_invalid_schema() -> None:
    p = StubProvider(mode="invalid_schema")
    out = await p.complete("hello")
    assert "broken" in out.text
