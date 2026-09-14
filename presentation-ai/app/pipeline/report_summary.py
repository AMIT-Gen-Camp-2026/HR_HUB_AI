"""Presentation-level reporting built only from existing pipeline output."""
from __future__ import annotations

import logging
import re
from collections import Counter
from typing import TYPE_CHECKING

from app.prompts.registry import PromptRegistry
from app.providers.base import ProviderAdapter
from app.schemas.presentation import Claim, ClaimVerification, Scores
from app.telemetry import record_call

if TYPE_CHECKING:
    from app.pipeline.extract_pptx import SlideContent

logger = logging.getLogger(__name__)

_ARABIC_RE = re.compile(r"[\u0600-\u06ff]")
_STATUS_NAMES = (
    "supported",
    "contradicted",
    "project_unsupported",
    "plausibility_flag",
    "unclear",
    "not_checkable",
)


def _is_arabic(claims: list[Claim]) -> bool:
    """Use the claim language as the report language signal, matching extraction."""
    return bool(_ARABIC_RE.search(" ".join(claim.text for claim in claims)))


def _counts(claims: list[Claim], verifications: list[ClaimVerification]) -> tuple[Counter[str], int, int, int]:
    """Return verdict, scoreable, evidence-backed, and provider-error counts."""
    by_id = {verification.claim_id: verification for verification in verifications}
    verdicts = Counter(verification.status for verification in verifications)
    scoreable = [
        verification
        for claim in claims
        if (verification := by_id.get(claim.claim_id)) is not None
        and verification.status != "not_checkable"
    ]
    return verdicts, len(scoreable), sum(bool(v.evidence) for v in scoreable), sum(
        v.verification_error is not None for v in scoreable
    )


def _english_evidence(scores: Scores, verdicts: Counter[str], total: int, evidence: int, errors: int) -> dict[str, str]:
    contradicted = verdicts["contradicted"]
    supported = verdicts["supported"]
    unclear = verdicts["unclear"]
    flagged = verdicts["plausibility_flag"]
    unsupported = verdicts["project_unsupported"]
    error_clause = f" {errors} claim(s) had a verification-tool error and were excluded from the accuracy denominator." if errors else ""
    return {
        "overall": (
            f"Overall is {scores.overall}, combining Fact Accuracy ({scores.fact_accuracy}), "
            f"Evidence Coverage ({scores.evidence_coverage}), and Reliability ({scores.claim_reliability}). "
            f"Across {total} scoreable claim(s), the verdicts include {supported} SUPPORTED, {contradicted} CONTRADICTED, "
            f"{unclear} UNCLEAR, {flagged} PLAUSIBILITY_FLAG, and {unsupported} PROJECT_UNSUPPORTED."
        ),
        "fact_accuracy": (
            f"Fact Accuracy is {scores.fact_accuracy}: {contradicted} of {total} scoreable claim(s) were CONTRADICTED, "
            f"while {supported} were SUPPORTED, {unclear} were UNCLEAR, {flagged} were PLAUSIBILITY_FLAG, and "
            f"{unsupported} were PROJECT_UNSUPPORTED.{error_clause}"
        ),
        "evidence_coverage": (
            f"Evidence Coverage is {scores.evidence_coverage} because {evidence} of {total} scoreable claim(s) have "
            f"attached concrete evidence; {total - evidence} do not."
        ),
        "reliability": (
            f"Reliability is {scores.claim_reliability} because it mirrors the importance-weighted Fact Accuracy calculation "
            f"for the {total} scoreable claim(s), including {contradicted} CONTRADICTED claim(s)."
        ),
    }


def _arabic_evidence(scores: Scores, verdicts: Counter[str], total: int, evidence: int, errors: int) -> dict[str, str]:
    contradicted = verdicts["contradicted"]
    supported = verdicts["supported"]
    unclear = verdicts["unclear"]
    flagged = verdicts["plausibility_flag"]
    unsupported = verdicts["project_unsupported"]
    error_clause = f" وتم استبعاد {errors} ادعاء/ادعاءات بها خطأ في أداة التحقق من مقام دقة الحقائق." if errors else ""
    return {
        "overall": (
            f"النتيجة الإجمالية هي {scores.overall}، وهي تجمع دقة الحقائق ({scores.fact_accuracy}) وتغطية الأدلة "
            f"({scores.evidence_coverage}) والموثوقية ({scores.claim_reliability}). من أصل {total} ادعاء قابل للتقييم، "
            f"توجد {supported} حالات SUPPORTED و{contradicted} حالات CONTRADICTED و{unclear} حالات UNCLEAR و"
            f"{flagged} حالات PLAUSIBILITY_FLAG و{unsupported} حالات PROJECT_UNSUPPORTED."
        ),
        "fact_accuracy": (
            f"دقة الحقائق هي {scores.fact_accuracy}: توجد {contradicted} ادعاءات CONTRADICTED من أصل {total} ادعاء قابل للتقييم، "
            f"مقابل {supported} SUPPORTED و{unclear} UNCLEAR و{flagged} PLAUSIBILITY_FLAG و{unsupported} PROJECT_UNSUPPORTED.{error_clause}"
        ),
        "evidence_coverage": (
            f"تغطية الأدلة هي {scores.evidence_coverage} لأن {evidence} من أصل {total} ادعاء قابل للتقييم لديه أدلة ملموسة مرفقة، "
            f"بينما {total - evidence} ليس لديه أدلة مرفقة."
        ),
        "reliability": (
            f"الموثوقية هي {scores.claim_reliability} لأنها تطابق حساب دقة الحقائق الموزون بالأهمية للادعاءات القابلة للتقييم وعددها {total}، "
            f"بما في ذلك {contradicted} ادعاء CONTRADICTED."
        ),
    }


def build_score_evidence(
    claims: list[Claim], verifications: list[ClaimVerification], scores: Scores
) -> dict[str, str]:
    """Explain score inputs exactly; this function never calls an AI provider."""
    verdicts, total, evidence, errors = _counts(claims, verifications)
    if _is_arabic(claims):
        return _arabic_evidence(scores, verdicts, total, evidence, errors)
    return _english_evidence(scores, verdicts, total, evidence, errors)


def _slide_context(slides: list[SlideContent]) -> str:
    blocks: list[str] = []
    for slide in slides:
        text = "\n".join(element.content for element in slide.elements)
        if slide.title:
            text = f"Title: {slide.title}\n{text}".strip()
        if text:
            blocks.append(f"Slide {slide.slide_number}:\n{text[:2000]}")
    return "\n\n".join(blocks)


def _fallback_brief(slides: list[SlideContent]) -> str:
    count = len(slides)
    return (
        f"This is a {count}-slide presentation based on the material extracted from its slides. "
        "It is organized as a slide-by-slide account of the presentation's stated topics and supporting details. "
        "The deck has an informative, technical tone. "
        "This overview describes the presentation content only and does not assess whether its claims are true."
    )


def generate_report_summary(
    claims: list[Claim],
    verifications: list[ClaimVerification],
    scores: Scores,
    slides: list[SlideContent],
    provider: ProviderAdapter,
    prompts: PromptRegistry,
) -> tuple[dict[str, str], str]:
    """Return score evidence plus an English-only presentation brief.

    The brief sees only extracted slide content. Any provider failure leaves the
    analysis successful and returns an English deterministic fallback.
    """
    score_evidence = build_score_evidence(claims, verifications, scores)
    fallback = _fallback_brief(slides)
    context = _slide_context(slides)
    if not context:
        return score_evidence, fallback

    try:
        rendered = prompts.render("report_summary", slide_count=len(slides), slide_content=context)
        with record_call("report_summary", provider.name, "", "report_summary.v1") as rec:
            result = provider.complete(prompt=rendered, temperature=0.0)
            rec.model_version = result.model_version
            rec.tokens_in, rec.tokens_out = result.tokens_in, result.tokens_out
        brief = (result.text or "").strip()
        return score_evidence, brief if brief else fallback
    except Exception as exc:
        logger.warning("Presentation brief generation failed; using fallback: %s", exc)
        return score_evidence, fallback
