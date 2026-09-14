"""Optional local LLM adapter (e.g. Ollama) for fully offline development — lets you
exercise the whole pipeline without touching the Gemini free-tier quota while writing
and debugging prompts. Not intended for production use (no grounding tool support,
so Track-1 fact-checking will always return empty grounding_sources here)."""
from __future__ import annotations

from app.providers.base import CompletionResult, ProviderAdapter
from config.settings import Settings


class LocalProvider(ProviderAdapter):
    name = "local"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # TODO: an OpenAI-compatible client pointed at settings.local_base_url (Ollama etc.)

    def complete(
        self,
        *,
        prompt: str,
        response_schema: dict | None = None,
        use_grounding: bool = False,
        temperature: float = 0.2,
    ) -> CompletionResult:
        # No grounding tool available locally — always return grounding_sources=[].
        # Track-1 callers must treat that as 'unclear', never fabricate a source.
        raise NotImplementedError("Wire up an OpenAI-compatible chat call to LOCAL_BASE_URL here.")

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("Use PROVIDER=hf for embeddings even when PROVIDER=local for text.")
