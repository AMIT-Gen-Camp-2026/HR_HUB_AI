"""Scenario 1 — hosted API.

Works with any OpenAI-compatible endpoint. Swap the base URL for Anthropic, Azure,
Together, Groq or anything else that speaks the same shape.
"""
from __future__ import annotations

import httpx
from pydantic import BaseModel

from app.errors import ProviderUnavailable
from app.providers.base import Completion, ProviderAdapter
from config.settings import Settings


class ApiProvider(ProviderAdapter):
    name = "api"

    def __init__(self, settings: Settings) -> None:
        self._model = settings.api_model
        self._client = httpx.AsyncClient(
            base_url=settings.api_base_url,
            headers={"Authorization": f"Bearer {settings.api_key}"},
            timeout=settings.api_timeout_seconds,
        )

    async def complete(
        self,
        prompt: str,
        *,
        schema: type[BaseModel] | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        timeout_seconds: int = 60,
    ) -> Completion:
        body: dict = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if schema is not None:
            # JSON mode. The structured-output layer still validates — never trust the flag alone.
            body["response_format"] = {"type": "json_object"}

        try:
            r = await self._client.post("/chat/completions", json=body, timeout=timeout_seconds)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"Hosted provider unreachable: {exc}") from exc

        data = r.json()
        usage = data.get("usage", {})
        return Completion(
            text=data["choices"][0]["message"]["content"],
            model_version=data.get("model", self._model),
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
            raw=data,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError(
            "Embeddings are served by the local BGE-M3 model, not the hosted API. "
            "See app/providers/embeddings.py"
        )

    async def healthcheck(self) -> bool:
        try:
            r = await self._client.get("/models", timeout=5)
            return r.status_code < 500
        except Exception:
            return False

    async def aclose(self) -> None:
        await self._client.aclose()
