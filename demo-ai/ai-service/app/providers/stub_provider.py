"""Scenario 4 — stub. The default in tests and in UI work.

Deterministic, offline, free. It can also be told to misbehave, so the failure paths
are testable:

    StubProvider(mode="timeout")
    StubProvider(mode="invalid_schema")
"""
from __future__ import annotations

import asyncio
import json
from typing import Literal

from pydantic import BaseModel

from app.errors import ProviderUnavailable
from app.providers.base import Completion, ProviderAdapter

CANNED_CV = {
    "personal": {"full_name": "Test Candidate", "email": None, "phone": None, "national_id": None},
    "education": [{"degree": "BSc Computer Science", "institution": "Cairo University", "year": 2018}],
    "experience": [
        {
            "title": "Data Analyst",
            "company": "Example Retail",
            "start": "2019-01",
            "end": "2022-06",
            "description": "Built dashboards and a recommendation prototype using Python and Pandas.",
        }
    ],
    "projects": [
        {
            "name": "Recommendation system",
            "description": "Developed a recommendation system using Python, Pandas, Scikit-learn and XGBoost.",
        }
    ],
    "certifications": [],
    "skills": [
        {"name": "Python", "source": "explicit", "evidence": {"section": "skills", "span": "Python, SQL"}, "confidence": 0.99},
        {"name": "SQL", "source": "explicit", "evidence": {"section": "skills", "span": "Python, SQL"}, "confidence": 0.99},
        {"name": "Pandas", "source": "inferred", "evidence": {"section": "projects", "span": "using Python, Pandas, Scikit-learn and XGBoost"}, "confidence": 0.92},
        {"name": "Scikit-learn", "source": "inferred", "evidence": {"section": "projects", "span": "using Python, Pandas, Scikit-learn and XGBoost"}, "confidence": 0.91},
        {"name": "XGBoost", "source": "inferred", "evidence": {"section": "projects", "span": "using Python, Pandas, Scikit-learn and XGBoost"}, "confidence": 0.90},
    ],
}


class StubProvider(ProviderAdapter):
    name = "stub"

    def __init__(self, mode: Literal["ok", "timeout", "invalid_schema"] = "ok") -> None:
        self._mode = mode

    async def complete(self, prompt: str, *, schema=None, **kwargs) -> Completion:
        if self._mode == "timeout":
            await asyncio.sleep(0.01)
            raise ProviderUnavailable("Simulated timeout")
        if self._mode == "invalid_schema":
            return Completion(text="Here is the CV data: {broken json", model_version="stub@1")
        return Completion(
            text=json.dumps(CANNED_CV, ensure_ascii=False),
            model_version="stub@1",
            tokens_in=len(prompt) // 4,
            tokens_out=400,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # Deterministic pseudo-embeddings so similarity tests are repeatable.
        return [[(hash(t + str(i)) % 1000) / 1000 for i in range(8)] for t in texts]

    async def healthcheck(self) -> bool:
        return True
