"""Local multilingual embedding model, per docs/DECISIONS.md section 6 and 11: runs on
this machine (sentence-transformers), NOT the paid HF Inference API — no rate limits,
no applicant text leaving the server, works for Arabic + English + mixed content.

Also serves as a pure-embeddings provider if PROVIDER=hf is selected; complete()
is intentionally unimplemented since this backend has no text-generation model.
"""
from __future__ import annotations

from functools import cached_property

from app.providers.base import CompletionResult, ProviderAdapter
from config.settings import Settings


class HFProvider(ProviderAdapter):
    name = "hf"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @cached_property
    def _model(self):
        # Loaded lazily and cached — sentence-transformers model load is expensive
        # (downloads + loads into memory), must happen once per process, never
        # per-request. The first embed() call will be slow; subsequent ones are fast.
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(
            self._settings.embedding_model, device=self._settings.embedding_device
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode(texts, normalize_embeddings=True).tolist()

    def complete(self, **kwargs) -> CompletionResult:
        raise NotImplementedError(
            "HFProvider is embeddings-only in this project. Use PROVIDER=api or "
            "PROVIDER=local for text generation."
        )