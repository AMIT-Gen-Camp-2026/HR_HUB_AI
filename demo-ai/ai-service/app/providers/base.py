"""The provider contract.

Swapping a model is a configuration change, never a code change. Nothing outside this
package may import a provider SDK, and nothing inside `app/pipeline/` may know which
provider it is talking to.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass
class Completion:
    """What every provider returns, whatever it is underneath."""

    text: str
    model_version: str
    tokens_in: int = 0
    tokens_out: int = 0
    raw: dict[str, Any] | None = None


class ProviderAdapter(ABC):
    """One interface, four implementations: api · hf · local · stub."""

    name: str = "base"

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        *,
        schema: type[T] | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        timeout_seconds: int = 60,
    ) -> Completion:
        """Return raw text. Schema enforcement happens in the structured-output layer,
        because not every provider supports JSON mode — see providers.yaml."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Batch embedding. Cached by content hash upstream."""

    async def healthcheck(self) -> bool:
        """Cheap reachability probe. Never raises."""
        return True

    async def aclose(self) -> None:
        """Release connections."""
        return None
