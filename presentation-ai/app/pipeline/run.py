"""Orchestrator - ties every pipeline stage together in order. This is the file
to read first to understand the whole flow (docs/DECISIONS.md section 8).
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any

from cachetools import LRUCache

from app.errors import (
    AppError,
    ClaimExtractionFailed,
    CorruptedFile,
    ExtractionFailed,
    FactCheckFailed,
    InvalidFile,
    ScoringFailed,
)
from app.pipeline import (
    claim_extraction,
    extract_pdf,
    extract_pptx,
    fact_check,
    normalize,
    postprocess,
    report_summary,
    scoring,
)
from app.prompts.registry import PromptRegistry
from app.providers.base import ProviderAdapter
from app.schemas.presentation import (
    CompletenessMeta,
    PresentationAnalysisResult,
    PresentationMeta,
    Summary,
)
from config.settings import Settings

logger = logging.getLogger(__name__)

# In-memory result cache resets on server restart by design.
_RESULT_CACHE: LRUCache = LRUCache(maxsize=50)


def _get_result_cache(max_size: Any) -> LRUCache:
    global _RESULT_CACHE
    if not isinstance(max_size, int) or max_size <= 0:
        size = 50
    else:
        size = max_size
    if _RESULT_CACHE.maxsize != size:
        new_cache: LRUCache = LRUCache(maxsize=size)
        for k, v in _RESULT_CACHE.items():
            new_cache[k] = v
        _RESULT_CACHE = new_cache
    return _RESULT_CACHE


def run_presentation_analysis(
    *,
    filename: str,
    content: bytes,
    provider: ProviderAdapter,
    prompts: PromptRegistry,
    settings: Settings,
    applicant_id: str | None = None,
    job_id: str | None = None,
) -> PresentationAnalysisResult:
    file_hash = hashlib.sha256(content).hexdigest()
    use_cache = bool(getattr(settings, "enable_result_cache", True) is True)
    if use_cache:
        cache = _get_result_cache(getattr(settings, "result_cache_max_size", 50))
        if file_hash in cache:
            logger.info("Cache hit for %s (hash %s)", filename, file_hash[:8])
            return cache[file_hash]
    # --- Extraction (deterministic) ---
    is_pdf = filename.lower().endswith(".pdf") or content.startswith(b"%PDF-")
    try:
        if is_pdf:
            extracted = extract_pdf.extract_pdf(content)
        else:
            extracted = extract_pptx.extract(content)
    except extract_pdf.PdfEncryptedError as exc:
        raise InvalidFile("The uploaded PDF file is password-protected.") from exc
    except extract_pdf.PdfPackageCorrupted as exc:
        raise CorruptedFile(f"The uploaded file is not a valid PDF package: {exc}") from exc
    except extract_pptx.PptxPackageCorrupted as exc:
        raise CorruptedFile("The uploaded file is not a valid .pptx package.") from exc
    except AppError:
        raise
    except Exception as exc:
        raise ExtractionFailed(f"Failed to extract presentation content: {exc}") from exc

    if extracted.slide_count == 0:
        raise ExtractionFailed("The presentation contains no slides.")

    normalized = normalize.normalize(extracted)
    slide_context_by_number = {
        s.slide_number: normalize.slide_to_prompt_text(s) for s in normalized.slides
    }

    # --- Claim extraction (AI) ---
    try:
        claims, failed_slides = claim_extraction.extract_claims(normalized.slides, provider, prompts)
    except AppError:
        raise
    except Exception as exc:
        raise ClaimExtractionFailed(f"Claim extraction failed: {exc}") from exc

    all_failed_slides = sorted(list(set(extracted.failed_slide_numbers) | set(failed_slides)))

    # --- Verification (AI, dispatched by track) ---
    try:
        verifications = fact_check.verify_claims(claims, provider, prompts, slide_context_by_number, settings)
    except AppError:
        raise
    except Exception as exc:
        raise FactCheckFailed(f"Claim verification failed: {exc}") from exc

    # --- Scoring (deterministic) ---
    try:
        scores = scoring.compute_scores(claims, verifications)
    except AppError:
        raise
    except Exception as exc:
        raise ScoringFailed(f"Score calculation failed: {exc}") from exc

    # --- Report summary (score explanation + presentation-level English brief) ---
    score_evidence, brief = report_summary.generate_report_summary(
        claims, verifications, scores, normalized.slides, provider, prompts
    )

    # --- Corrections (AI, contradicted-only) + issues/questions (deterministic) ---
    claim_by_id = {c.claim_id: c for c in claims}
    corrections: dict[str, str] = {}
    for verification in verifications:
        if verification.status != "contradicted":
            continue
        claim = claim_by_id.get(verification.claim_id)
        if claim is None:
            continue
        correction = postprocess.generate_correction(claim, verification, provider, prompts)
        if correction is not None:
            corrections[verification.claim_id] = correction.text

    issues = postprocess.build_issues(claims, verifications, corrections)
    interview_questions = postprocess.build_interview_questions(claims, verifications)

    # --- Summary ---
    summary = Summary(total_claims=len(claims))
    for verification in verifications:
        if hasattr(summary, verification.status):
            setattr(summary, verification.status, getattr(summary, verification.status) + 1)

    # --- Completeness & Status ---
    slides_failed_count = len(all_failed_slides)
    slides_processed_count = max(0, extracted.slide_count - slides_failed_count)

    if slides_processed_count == 0 or extracted.slide_count == 0:
        comp_status = "no_extractable_content"
        comp_message = "No text content could be extracted from this presentation. It may contain only images."
    elif slides_failed_count > 0:
        comp_status = "partial"
        comp_message = f"{slides_failed_count} slide(s) contained no extractable text."
    else:
        comp_status = "ok"
        comp_message = None

    completeness = CompletenessMeta(
        slides_total=extracted.slide_count,
        slides_processed=slides_processed_count,
        slides_failed=slides_failed_count,
        status=comp_status,
        message=comp_message,
    )

    status = "completed" if slides_failed_count == 0 else "partial"

    result = PresentationAnalysisResult(
        analysis_id=f"ANL-{uuid.uuid4().hex[:12]}",
        status=status,
        completeness=completeness,
        presentation=PresentationMeta(filename=filename, slide_count=extracted.slide_count),
        scores=scores,
        summary=summary,
        score_evidence=score_evidence,
        brief=brief,
        claims=claims,
        verifications=verifications,
        issues=issues,
        suggested_interview_questions=interview_questions,
    )

    if use_cache:
        cache = _get_result_cache(getattr(settings, "result_cache_max_size", 50))
        cache[file_hash] = result

    return result
