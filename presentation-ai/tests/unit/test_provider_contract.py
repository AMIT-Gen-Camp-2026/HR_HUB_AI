"""Runs the same behavioral checks against every provider that CAN run without real
credentials (currently just stub_provider) — guarantees swapping providers never
silently breaks the pipeline's expectations of the ProviderAdapter interface."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.providers import api_provider
from app.providers.api_provider import GeminiProvider
from app.providers.stub_provider import StubProvider
from config.settings import Settings


def test_default_grounding_model_is_current_flash_model():
    assert Settings().gemini_grounding_model == "gemini-3.6-flash"


def test_stub_provider_complete_returns_completion_result():
    provider = StubProvider(Settings(provider="stub"))
    result = provider.complete(prompt="anything")
    assert result.text
    assert result.model_version


def test_stub_provider_grounding_flag_populates_sources():
    provider = StubProvider(Settings(provider="stub"))
    grounded = provider.complete(prompt="x", use_grounding=True)
    ungrounded = provider.complete(prompt="x", use_grounding=False)
    assert grounded.grounding_sources
    assert not ungrounded.grounding_sources


def test_stub_provider_embed_returns_one_vector_per_text():
    provider = StubProvider(Settings(provider="stub"))
    vectors = provider.embed(["a", "b", "c"])
    assert len(vectors) == 3


def test_gemini_provider_selects_grounding_model_only_for_grounded_calls(monkeypatch):
    generated = []

    class FakeModels:
        def generate_content(self, **kwargs):
            generated.append(kwargs)
            return SimpleNamespace(text="answer", candidates=[], usage_metadata=None)

    fake_client = SimpleNamespace(models=FakeModels())
    monkeypatch.setattr(api_provider.genai, "Client", lambda **_: fake_client)
    monkeypatch.setattr(api_provider, "wait_for_gemini_pacing", lambda _: None)
    settings = Settings(
        provider="api",
        gemini_api_key="test-key",
        gemini_model="standard-test-model",
        gemini_grounding_model="grounding-test-model",
    )
    provider = GeminiProvider(settings)

    ordinary = provider.complete(prompt="ordinary", use_grounding=False)
    grounded = provider.complete(prompt="grounded", use_grounding=True)

    assert generated[0]["model"] == settings.gemini_model
    assert generated[1]["model"] == settings.gemini_grounding_model
    assert ordinary.model_version == settings.gemini_model
    assert grounded.model_version == settings.gemini_grounding_model
    assert provider.model_for_completion(use_grounding=True) == settings.gemini_grounding_model
