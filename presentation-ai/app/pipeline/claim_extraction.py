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
from rapidfuzz import fuzz

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


def _slide_has_content(slide: SlideContent) -> bool:
    if slide.extraction_error:
        return False
    return any(el.content.strip() for el in slide.elements) or bool(slide.title and slide.title.strip())


def _deduplicate_claims(
    raw_items: list[tuple],
    threshold: int,
) -> list[tuple]:
    """Remove near-duplicate claims using fuzzy string matching.

    For each candidate, compare against all already-accepted claims.
    A candidate is a duplicate when:
      - Its claim_type matches exactly (case-insensitive), AND
      - rapidfuzz.fuzz.ratio() on the normalised text exceeds *threshold*.

    The first occurrence is always kept; subsequent near-duplicates are discarded.
    Passing threshold=0 disables deduplication and returns the original list unchanged.

    Args:
        raw_items: List of (raw_claim, slide_number) pairs assembled from all batches.
        threshold: Similarity threshold (0-100). 0 means disabled.

    Returns:
        Filtered list preserving order, with duplicates removed.
    """
    if threshold == 0:
        return raw_items

    accepted: list[tuple] = []

    for item in raw_items:
        raw, sn = item
        if isinstance(raw, RawClaimOutput):
            candidate_text = raw.text.strip().lower()
            candidate_type = (raw.claim_type or "").strip().lower()
        else:
            candidate_text = (raw.get("text") or "").strip().lower()
            candidate_type = (raw.get("claim_type") or "").strip().lower()

        is_duplicate = False
        for accepted_raw, _ in accepted:
            if isinstance(accepted_raw, RawClaimOutput):
                seen_text = accepted_raw.text.strip().lower()
                seen_type = (accepted_raw.claim_type or "").strip().lower()
            else:
                seen_text = (accepted_raw.get("text") or "").strip().lower()
                seen_type = (accepted_raw.get("claim_type") or "").strip().lower()

            # Only deduplicate when both text similarity AND claim_type match.
            if candidate_type == seen_type and fuzz.ratio(candidate_text, seen_text) > threshold:
                is_duplicate = True
                break

        if is_duplicate:
            logger.info(
                "Deduplicating claim on slide %s (similar to existing claim): %r",
                sn,
                candidate_text[:80],
            )
        else:
            accepted.append(item)

    return accepted


def extract_claims(
    slides: list[SlideContent],
    provider: ProviderAdapter,
    prompts: PromptRegistry,
) -> tuple[list[Claim], list[int]]:
    claims: list[Claim] = []
    failed_slides: list[int] = []
    pacing = get_settings().gemini_call_pacing_seconds
    extraction_calls = 0

    valid_slides: list[SlideContent] = []
    for s in slides:
        if _slide_has_content(s):
            valid_slides.append(s)
        else:
            failed_slides.append(s.slide_number)

    batch_size = getattr(get_settings(), "claim_extraction_batch_size", _DEFAULT_BATCH_SIZE)

    # Phase 1 - collect raw items from all batches (no ID assignment yet).
    raw_items: list[tuple] = []

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
                    prompt=rendered,
                    response_schema=list[RawClaimOutput],
                    temperature=0.0,
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
            raw_items.append((raw, sn))

    # Phase 2 - deduplicate before ID assignment so IDs are always sequential.
    threshold = getattr(get_settings(), "claim_deduplication_threshold", 90)
    deduplicated = _deduplicate_claims(raw_items, threshold)

    logger.info(
        "Claim deduplication: %d claims before, %d after (removed %d duplicates)",
        len(raw_items),
        len(deduplicated),
        len(raw_items) - len(deduplicated),
    )

    # Phase 3 - coerce + assign sequential IDs.
    counter = 1
    for raw, sn in deduplicated:
        claim = _coerce_claim(raw, sn, f"CLM-{counter:03d}")
        if claim is not None:
            claims.append(claim)
            counter += 1

    return claims, failed_slides