"""[AI] Extract + classify claims per slide, batched multiple slides per call. Resilient
by design: a malformed response for a batch is logged and skipped rather than
aborting the whole analysis - a partial report is more useful to HR than none.

Includes inter-call pacing (docs/DECISIONS.md section 18): the free-tier RPM (requests
per minute) limit observed in practice is tight enough that several consecutive slide
extractions back-to-back can trigger a 429 even when the daily quota is nowhere near
exhausted. A short sleep between calls keeps us comfortably under that RPM ceiling.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, TypeVar

from pydantic import BaseModel, Field

from app.errors import DailyQuotaExceeded
from app.pipeline.extract_pptx import SlideContent
from app.pipeline.normalize import slide_to_prompt_text
from app.prompts.registry import PromptRegistry
from app.providers.base import ProviderAdapter
from app.schemas.presentation import Claim
from app.taxonomy.canonicalize import canonicalize_property, is_known_claim_type
from app.telemetry import record_call
from config.settings import get_settings

logger = logging.getLogger(__name__)

_VALID_TRACKS = {"objective", "project_specific"}
_VALID_IMPORTANCE = {"high", "medium", "low"}
_DEFAULT_BATCH_SIZE = 4

T = TypeVar("T")


def _chunk(items: list[T], size: int) -> list[list[T]]:
    if size <= 0:
        size = _DEFAULT_BATCH_SIZE
    return [items[i : i + size] for i in range(0, len(items), size)]


class RawClaimOutput(BaseModel):
    slide_number: int
    text: str
    claim_type: str = "capability"
    track: str = "project_specific"
    importance: str = "medium"
    subject: str | None = None
    property: str | None = None
    value: float | str | None = None
    unit: str | None = None


def _coerce_claim(raw: dict | RawClaimOutput, slide_number: int, claim_id: str) -> Claim | None:
    if isinstance(raw, RawClaimOutput):
        raw_dict = raw.model_dump()
    elif isinstance(raw, dict):
        raw_dict = raw
    else:
        return None

    text = (raw_dict.get("text") or "").strip()
    if not text:
        return None

    claim_type = raw_dict.get("claim_type")
    if not is_known_claim_type(claim_type):
        logger.warning(
            "Unknown claim_type %r on slide %s - defaulting to 'capability'",
            claim_type,
            slide_number,
        )
        claim_type = "capability"

    track = raw_dict.get("track")
    if track not in _VALID_TRACKS:
        logger.warning(
            "Unknown/missing track %r on slide %s - defaulting to 'project_specific'",
            track,
            slide_number,
        )
        track = "project_specific"

    importance = raw_dict.get("importance")
    if importance not in _VALID_IMPORTANCE:
        importance = "medium"

    prop = raw_dict.get("property")
    if prop:
        prop = canonicalize_property(str(prop))

    return Claim(
        claim_id=claim_id,
        slide_number=slide_number,
        text=text,
        claim_type=claim_type,
        track=track,
        importance=importance,
        subject=raw_dict.get("subject"),
        property=prop,
        value=raw_dict.get("value"),
        unit=raw_dict.get("unit"),
    )


def extract_claims(
    slides: list[SlideContent],
    provider: ProviderAdapter,
    prompts: PromptRegistry,
) -> tuple[list[Claim], list[int]]:
    claims: list[Claim] = []
    failed_slides: list[int] = []
    counter = 1
    pacing = get_settings().gemini_call_pacing_seconds
    extraction_calls = 0

    valid_slides = [s for s in slides if slide_to_prompt_text(s).strip()]
    batch_size = getattr(get_settings(), "claim_extraction_batch_size", _DEFAULT_BATCH_SIZE)

    for batch in _chunk(valid_slides, batch_size):
        if extraction_calls > 0 and pacing > 0:
            time.sleep(pacing)
        extraction_calls += 1

        rendered = prompts.render(
            "claim_extract",
            version="v4",
            slides=[
                {
                    "slide_number": s.slide_number,
                    "slide_text": slide_to_prompt_text(s),
                }
                for s in batch
            ],
        )

        try:
            with record_call("claim_extraction", provider.name, "", "claim_extract.v4") as rec:
                result = provider.complete(
                    prompt=rendered, response_schema=list[RawClaimOutput]
                )
                rec.model_version = result.model_version
                rec.tokens_in, rec.tokens_out = result.tokens_in, result.tokens_out

            items = json.loads(result.text) if result.text else []
            if not isinstance(items, list):
                raise ValueError("Expected a JSON array")
        except DailyQuotaExceeded:
            raise
        except Exception:
            batch_numbers = [s.slide_number for s in batch]
            logger.warning(
                "Claim extraction failed for slides %s - skipping this batch",
                batch_numbers,
                exc_info=True,
            )
            failed_slides.extend(batch_numbers)
            continue

        for raw in items:
            raw_dict = raw.model_dump() if isinstance(raw, RawClaimOutput) else (raw if isinstance(raw, dict) else {})
            sn = raw_dict.get("slide_number")
            if not isinstance(sn, int):
                try:
                    sn = int(sn)
                except (TypeError, ValueError):
                    logger.warning("Missing or invalid slide_number %r in raw claim item - skipping", sn)
                    continue

            claim = _coerce_claim(raw, sn, f"CLM-{counter:03d}")
            if claim is not None:
                claims.append(claim)
                counter += 1

    return claims, failed_slides
