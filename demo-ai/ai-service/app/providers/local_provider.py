"""Scenario 3 — local. Ollama or vLLM on your own machine.

    ollama pull qwen2.5:7b-instruct
    PROVIDER=local make run

Both Ollama and vLLM expose an OpenAI-compatible endpoint, so this is deliberately
the same shape as ApiProvider — the difference is the base URL and that there is no key.
"""
from __future__ import annotations

import httpx
from pydantic import BaseModel

from app.errors import ProviderUnavailable
from app.providers.base import Completion, ProviderAdapter
from config.settings import Settings


class LocalProvider(ProviderAdapter):
    name = "local"

    def __init__(self, settings: Settings) -> None:
        self._model = settings.local_model
        self._client = httpx.AsyncClient(
            base_url=settings.local_base_url,
            timeout=settings.local_timeout_seconds,
        )

    async def complete(
        self,
        prompt: str,
        *,
        schema: type[BaseModel] | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        timeout_seconds: int = 120,
    ) -> Completion:
        body: dict = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if schema is not None:
            body["response_format"] = {"type": "json_object"}

        try:
            r = await self._client.post("/chat/completions", json=body, timeout=timeout_seconds)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(
                f"Local model unreachable at {self._client.base_url}. Is Ollama running? ({exc})"
            ) from exc

        data = r.json()
        usage = data.get("usage", {})
        return Completion(
            text=data["choices"][0]["message"]["content"],
            model_version=f"{self._model}@local",
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
            raw=data,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]

        model = SentenceTransformer("BAAI/bge-m3")
        return model.encode(texts, normalize_embeddings=True).tolist()

    async def healthcheck(self) -> bool:
        try:
            r = await self._client.get("/models", timeout=3)
            return r.status_code < 500
        except Exception:
            return False

    async def aclose(self) -> None:
        await self._client.aclose()
