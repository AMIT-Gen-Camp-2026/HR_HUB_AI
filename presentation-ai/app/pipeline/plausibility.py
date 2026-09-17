"""[AI + Deterministic] Track B - project-specific claims.

- Arithmetic & consistency checks: resolves to status='supported', verification_basis='internal_math_check',
  and attaches an Evidence entry.
- Contextual plausibility: resolves to status='project_unsupported' or 'plausibility_flag',
  with verification_basis='plausibility_heuristic_only'.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from app.errors import DailyQuotaExceeded
from app.prompts.registry import PromptRegistry
from app.providers.base import ProviderAdapter
from app.schemas.presentation import Claim, ClaimVerification, Evidence
from app.telemetry import record_call

logger = logging.getLogger(__name__)

_FLAGGED_METRICS = {"accuracy", "precision", "recall", "f1_score", "r2_score"}
_ROUND_THRESHOLD = 99.5
_FALLBACK_REASON = "Self-reported project/demo claim with no external ground truth; assessed as plausible."
_FAILURE_REASON = (
    "Plausibility judgment could not be completed due to an internal model error; "
    "requires manual review."
)

_CONTEXT_EXPECTED_TYPES = {"performance", "dataset"}
BATCH_SIZE = 4


class RawPlausibilityOutput(BaseModel):
    flagged: bool = False
    reason: str = Field(default=_FALLBACK_REASON)
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)


class RawPlausibilityItem(BaseModel):
    claim_id: str
    flagged: bool = False
    reason: str = Field(default=_FALLBACK_REASON)
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)


def check_internal_math_consistency(claim: Claim, slide_context: str) -> tuple[bool, str] | None:
    """Checks if a claim's stated count and percentage match each other or the slide total."""
    count: float | None = None
    pct: float | None = None
    tot: float | None = None

    # Match count and pct from claim text
    # e.g., "4 (16%)", "4 failed (16%)", "4 defects isolated (16%)", "16% (4 of 25)"
    m1 = re.search(r"(\d+(?:\.\d+)?)\s*(?:[a-zA-Z\s_-]*?)\s*\(\s*(\d+(?:\.\d+)?)\s*%\s*\)", claim.text)
    m2 = re.search(r"(\d+(?:\.\d+)?)\s*%\s*\(\s*(\d+(?:\.\d+)?)\s*(?:[a-zA-Z\s_-]*?)\)", claim.text)
    m3 = re.search(r"(\d+(?:\.\d+)?)\s*(?:out\s+of|\/)\s*(\d+(?:\.\d+)?).*?(\d+(?:\.\d+)?)\s*%", claim.text, re.IGNORECASE)
    m4 = re.search(r"(\d+(?:\.\d+)?)\s*%.*?(\d+(?:\.\d+)?)\s*(?:out\s+of|\/)\s*(\d+(?:\.\d+)?)", claim.text, re.IGNORECASE)

    if m1:
        count = float(m1.group(1))
        pct = float(m1.group(2))
    elif m2:
        pct = float(m2.group(1))
        count = float(m2.group(2))
    elif m3:
        count = float(m3.group(1))
        tot = float(m3.group(2))
        pct = float(m3.group(3))
    elif m4:
        pct = float(m4.group(1))
        count = float(m4.group(2))
        tot = float(m4.group(3))

    if count is not None and pct is not None:
        if tot is None:
            # Check claim text first for total
            tot_in_claim = re.search(r"(?:total\s*(?:of|:)?\s*|out\s+of\s+|\/\s*)(\d+(?:\.\d+)?)", claim.text, re.IGNORECASE)
            if tot_in_claim:
                tot = float(tot_in_claim.group(1))

        if tot is None and slide_context:
            # Check slide context for total
            matches = re.findall(r"(?:total\s*(?:of|:|defects|cases|tests|items|bugs)?\s*|out\s+of\s+|\/\s*|N\s*=\s*)(\d+(?:\.\d+)?)", slide_context, re.IGNORECASE)
            if matches:
                for match in matches:
                    val = float(match)
                    if val >= count and val > 0:
                        tot = val
                        break

            if tot is None:
                # Also check reverse pattern e.g. "25 total" or "25 Total"
                rev_match = re.search(r"(\d+(?:\.\d+)?)\s+total", slide_context, re.IGNORECASE)
                if rev_match:
                    val = float(rev_match.group(1))
                    if val >= count and val > 0:
                        tot = val

        if tot is not None and tot > 0:
            calc_pct = round((count / tot) * 100, 1)
            count_display = int(count) if count.is_integer() else count
            tot_display = int(tot) if tot.is_integer() else tot
            if abs(calc_pct - pct) <= 1.0:
                return True, f"Internal arithmetic verified: {count_display}/{tot_display} = {pct}%."
            else:
                return False, f"Internal arithmetic inconsistency: {count_display}/{tot_display} is {calc_pct}%, but claim states {pct}%."

    return None


def hard_rules(claim: Claim) -> str | None:
    """Returns a flag reason string if a deterministic rule fires, else None."""
    if claim.property in _FLAGGED_METRICS and claim.value is not None:
        try:
            value = float(claim.value)
        except (TypeError, ValueError):
            value = None
        if value is not None:
            if claim.unit == "%" and value >= _ROUND_THRESHOLD:
                return (
                    f"Reported {claim.property} of {value}% is at or above the "
                    f"{_ROUND_THRESHOLD}% threshold treated as suspiciously perfect."
                )
            if claim.unit is None and value >= (_ROUND_THRESHOLD / 100):
                return (
                    f"Reported {claim.property} of {value} is at or above "
                    f"{_ROUND_THRESHOLD / 100} on a 0-1 scale, treated as suspiciously perfect."
                )

    if (
        claim.claim_type in _CONTEXT_EXPECTED_TYPES
        and claim.subject is None
        and claim.property is None
    ):
        return "Claim states a measurable result with no surrounding context (no subject or measurable property identified)."

    return None


def _contextual_judgment(
    claim: Claim,
    slide_context: str,
    provider: ProviderAdapter,
    prompts: PromptRegistry,
) -> ClaimVerification:
    """Single-claim contextual judgment fallback."""
    math_result = check_internal_math_consistency(claim, slide_context)
    if math_result is not None:
        is_ok, reason = math_result
        status = "supported" if is_ok else "plausibility_flag"
        evidence = [
            Evidence(
                source_type="trusted_technical",
                source_url="internal://math-consistency-check",
                snippet=reason,
            )
        ]
        return ClaimVerification(
            claim_id=claim.claim_id,
            status=status,
            confidence=1.0 if is_ok else 0.95,
            reason=reason,
            evidence=evidence,
            verification_basis="internal_math_check",
        )

    rendered = prompts.render(
        "plausibility_judgment",
        version="v1",
        claim_text=claim.text,
        claim_type=claim.claim_type,
        slide_context=slide_context,
    )
    try:
        with record_call("plausibility", provider.name, "", "plausibility_judgment.v1") as rec:
            result = provider.complete(
                prompt=rendered, response_schema=RawPlausibilityOutput, temperature=0.0
            )
            rec.model_version = result.model_version
            rec.tokens_in, rec.tokens_out = result.tokens_in, result.tokens_out

        text = result.text if isinstance(result.text, str) else ""
        parsed = json.loads(text) if text else {}
        flagged = bool(parsed.get("flagged", False))
        confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.9))))
        reason = (parsed.get("reason") or "").strip() or _FALLBACK_REASON
    except DailyQuotaExceeded:
        raise
    except Exception as exc:
        logger.warning(
            "Single plausibility judgment failed for claim %s: %s - reporting as unclear",
            claim.claim_id,
            exc,
            exc_info=True,
        )
        return ClaimVerification(
            claim_id=claim.claim_id,
            status="unclear",
            confidence=0.0,
            reason=_FAILURE_REASON,
            evidence=[],
            verification_basis="plausibility_heuristic_only",
        )

    status = "plausibility_flag" if flagged else "project_unsupported"
    return ClaimVerification(
        claim_id=claim.claim_id,
        status=status,
        confidence=confidence,
        reason=reason,
        evidence=[],
        verification_basis="plausibility_heuristic_only",
    )


def _evaluate_batch_chunk(
    chunk: list[tuple[Claim, str]],
    provider: ProviderAdapter,
    prompts: PromptRegistry,
) -> dict[str, ClaimVerification]:
    """Evaluates a chunk of up to BATCH_SIZE claims in a single LLM call."""
    payload = [
        {
            "claim_id": c.claim_id,
            "claim_text": c.text,
            "claim_type": c.claim_type,
            "slide_context": ctx,
        }
        for c, ctx in chunk
    ]

    rendered = prompts.render(
        "plausibility_judgment",
        version="v2",
        claims=payload,
    )

    try:
        with record_call("plausibility", provider.name, "", "plausibility_judgment.v2") as rec:
            result = provider.complete(
                prompt=rendered,
                response_schema=list[RawPlausibilityItem],
                temperature=0.0,
            )
            rec.model_version = result.model_version
            rec.tokens_in, rec.tokens_out = result.tokens_in, result.tokens_out

        text = result.text if isinstance(result.text, str) else ""
        items = json.loads(text) if text else []
        if not isinstance(items, list):
            raise ValueError(f"Expected list of items, got {type(items).__name__}")

        results: dict[str, ClaimVerification] = {}
        for item in items:
            cid = item.get("claim_id")
            if not cid:
                continue
            flagged = bool(item.get("flagged", False))
            confidence = max(0.0, min(1.0, float(item.get("confidence", 0.9))))
            reason = (item.get("reason") or "").strip() or _FALLBACK_REASON
            status = "plausibility_flag" if flagged else "project_unsupported"
            results[cid] = ClaimVerification(
                claim_id=cid,
                status=status,
                confidence=confidence,
                reason=reason,
                evidence=[],
                verification_basis="plausibility_heuristic_only",
            )

        for c, _ in chunk:
            if c.claim_id not in results:
                raise ValueError(f"Missing claim_id {c.claim_id} in batch response")

        return results

    except DailyQuotaExceeded:
        raise
    except Exception as exc:
        logger.warning(
            "Batch plausibility chunk failed (%s), falling back to individual calls for %d claims",
            exc,
            len(chunk),
            exc_info=True,
        )
        fallback_results: dict[str, ClaimVerification] = {}
        for c, ctx in chunk:
            fallback_results[c.claim_id] = _contextual_judgment(c, ctx, provider, prompts)
        return fallback_results


def verify_batch(
    claims_with_context: list[tuple[Claim, str]],
    provider: ProviderAdapter,
    prompts: PromptRegistry,
) -> list[ClaimVerification]:
    """Batched verification for all project-specific claims."""
    verifications: dict[str, ClaimVerification] = {}
    needs_contextual: list[tuple[Claim, str]] = []

    for claim, context in claims_with_context:
        # Check internal arithmetic first
        math_result = check_internal_math_consistency(claim, context)
        if math_result is not None:
            is_ok, reason = math_result
            status = "supported" if is_ok else "plausibility_flag"
            evidence = [
                Evidence(
                    source_type="trusted_technical",
                    source_url="internal://math-consistency-check",
                    snippet=reason,
                )
            ]
            verifications[claim.claim_id] = ClaimVerification(
                claim_id=claim.claim_id,
                status=status,
                confidence=1.0 if is_ok else 0.95,
                reason=reason,
                evidence=evidence,
                verification_basis="internal_math_check",
            )
            continue

        hard_reason = hard_rules(claim)
        if hard_reason is not None:
            verifications[claim.claim_id] = ClaimVerification(
                claim_id=claim.claim_id,
                status="plausibility_flag",
                confidence=0.9,
                reason=hard_reason,
                evidence=[],
                verification_basis="plausibility_heuristic_only",
            )
        else:
            needs_contextual.append((claim, context))

    for i in range(0, len(needs_contextual), BATCH_SIZE):
        chunk = needs_contextual[i : i + BATCH_SIZE]
        chunk_results = _evaluate_batch_chunk(chunk, provider, prompts)
        for cid, ver in chunk_results.items():
            if cid not in verifications:
                verifications[cid] = ver

    return [
        verifications[claim.claim_id]
        for claim, _ in claims_with_context
        if claim.claim_id in verifications
    ]


def verify(
    claim: Claim,
    slide_context: str,
    provider: ProviderAdapter,
    prompts: PromptRegistry,
) -> ClaimVerification:
    """Single claim verification entry point."""
    math_result = check_internal_math_consistency(claim, slide_context)
    if math_result is not None:
        is_ok, reason = math_result
        status = "supported" if is_ok else "plausibility_flag"
        evidence = [
            Evidence(
                source_type="trusted_technical",
                source_url="internal://math-consistency-check",
                snippet=reason,
            )
        ]
        return ClaimVerification(
            claim_id=claim.claim_id,
            status=status,
            confidence=1.0 if is_ok else 0.95,
            reason=reason,
            evidence=evidence,
            verification_basis="internal_math_check",
        )

    hard_reason = hard_rules(claim)
    if hard_reason is not None:
        return ClaimVerification(
            claim_id=claim.claim_id,
            status="plausibility_flag",
            confidence=0.9,
            reason=hard_reason,
            evidence=[],
            verification_basis="plausibility_heuristic_only",
        )
    return _contextual_judgment(claim, slide_context, provider, prompts)
