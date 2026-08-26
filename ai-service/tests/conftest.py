from __future__ import annotations

import pytest

from app.prompts.registry import PromptRegistry
from app.providers.stub_provider import StubProvider
from config.settings import get_settings


@pytest.fixture
def provider() -> StubProvider:
    return StubProvider()


@pytest.fixture
def prompts() -> PromptRegistry:
    return PromptRegistry(get_settings().prompts_dir)
