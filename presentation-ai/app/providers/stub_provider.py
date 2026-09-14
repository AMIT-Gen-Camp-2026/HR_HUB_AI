"""Fake provider — canned, deterministic responses, zero network calls. Used by unit
tests, CI, and local smoke-testing. NEVER used in production.
"""
from __future__ import annotations

import json
from typing import Any, get_args, get_origin

from app.providers.base import CompletionResult, ProviderAdapter
from config.settings import Settings


class StubProvider(ProviderAdapter):
    name = "stub"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def complete(
        self,
        *,
        prompt: str,
        response_schema: Any | None = None,
        use_grounding: bool = False,
        temperature: float = 0.2,
    ) -> CompletionResult:
        prompt_lower = prompt.lower()
        schema_str = str(response_schema).lower()

        if "presentation overview" in prompt_lower or "slide_content_start" in prompt_lower:
            canned_text = (
                "This is a presentation about the material described in its slides. "
                "It is organized around the deck's stated technical topics and supporting details. "
                "The tone is informative and technical. "
                "This overview describes the presentation content without evaluating its claims."
            )

        elif (
            "rawplausibilityitem" in schema_str
            or "claims to evaluate" in prompt_lower
            or ("plausibility" in prompt_lower and "claim id:" in prompt_lower)
        ):
            # Extract claim IDs from prompt if present
            canned_items = []
            for line in prompt.splitlines():
                if "Claim ID:" in line:
                    cid = line.split("Claim ID:", 1)[1].strip()
                    canned_items.append({
                        "claim_id": cid,
                        "flagged": True,
                        "reason": "stub_provider: reported result requires verification.",
                        "confidence": 0.6,
                    })
            if not canned_items:
                canned_items = [{
                    "claim_id": "CLM-001",
                    "flagged": True,
                    "reason": "stub_provider: reported result requires verification.",
                    "confidence": 0.6,
                }]
            canned_text = json.dumps(canned_items)

        elif "rawplausibilityoutput" in schema_str or ("flagged" in prompt_lower and "plausibility" in prompt_lower):
            canned_text = json.dumps({
                "flagged": True,
                "reason": "stub_provider: 96% is a suspiciously round/high result with no stated benchmark.",
                "confidence": 0.6,
            })

        elif (
            "rawclaimoutput" in schema_str
            or "claim_extract" in prompt_lower
            or "extracting verifiable" in prompt_lower
            or "extract verifiable" in prompt_lower
            or "presentation_content" in prompt_lower
        ):
            canned_text = json.dumps([
                {
                    "slide_number": 1,
                    "text": "Our CNN model achieved 96% accuracy.",
                    "claim_type": "performance",
                    "track": "project_specific",
                    "importance": "high",
                    "subject": "model",
                    "property": "accuracy",
                    "value": 96,
                    "unit": "%",
                }
            ])

        elif '"status"' in prompt or "fact_check" in prompt_lower or use_grounding:
            canned_text = json.dumps({
                "status": "unclear",
                "confidence": 0.0,
                "reason": "stub_provider: no real fact-check performed.",
            })

        elif "neutral sentence" in prompt_lower or "correction" in prompt_lower:
            canned_text = "No verified value was found in the available evidence."

        else:
            canned_text = json.dumps({"note": "stub_provider canned response"})

        return CompletionResult(
            text=canned_text,
            model_version="stub-0",
            tokens_in=10,
            tokens_out=10,
            grounding_sources=[{"url": "https://example.com/stub-source", "title": "Stub source"}]
            if use_grounding else [],
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 8 for _ in texts]
