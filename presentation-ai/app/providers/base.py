"""The provider contract. Every backend (api_provider/hf_provider/local_provider/
stub_provider) implements this ABC identically, so app/pipeline/* code never knows
or cares which one is actually running.

Keep this interface small and stable — it is the seam that lets tests run against
stub_provider with zero network calls while production runs against api_provider.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CompletionResult:
    text: str
    model_version: str
    tokens_in: int = 0
    tokens_out: int = 0
    grounding_sources: list[dict] = field(default_factory=list)
    """Populated only when a web-search/grounding tool was used (Track-1 fact-check).
    Each entry: {"url": str, "title": str}. Empty list => no external source was
    found, and the caller MUST treat the verdict as 'unclear', never 'contradicted'."""
    parsed: Any = None


class ProviderAdapter(ABC):
    name: str

    def model_for_completion(self, *, use_grounding: bool = False) -> str:
        """Return the configured model for telemetry before a completion starts.

        Providers without a model-specific configuration may leave this blank.
        """
        return ""

    @abstractmethod
    def complete(
        self,
        *,
        prompt: str,
        response_schema: Any | None = None,
        use_grounding: bool = False,
        temperature: float = 0.2,
    ) -> CompletionResult:
        """One text-generation call. `response_schema` is a JSON-schema dict or Pydantic model.
        When given, the provider must return valid JSON matching it (or raise). Grounding
        is only meaningful for Track-1 fact-checking; providers that can't ground
        (stub, local) should return an empty grounding_sources list."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Batch embedding call, used for evidence/claim semantic matching."""
