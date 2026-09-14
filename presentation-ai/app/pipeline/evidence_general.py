"""[AI] Track A - objective claims, verified via mandatory web grounding.

Hard rule enforced HERE IN CODE, not just in the prompt (docs/DECISIONS.md section 9):
a 'supported'/'contradicted' verdict without a real grounding source AND sufficient
confidence is force-downgraded to 'unclear'. The model's self-reported status is
never trusted blindly.

A grounding quota failure degrades gracefully to 'unclear' with verification_error="search_quota_exhausted"
so infrastructure limitations are explicitly separated from candidate content accuracy.
"""
from __future__ import annotations

import json
import logging

from app.errors import DailyQuotaExceeded
from app.prompts.registry import PromptRegistry
from app.providers.base import ProviderAdapter
from app.providers.search.tavily_provider import TavilySearchProvider
from app.schemas.presentation import Claim, ClaimVerification, Evidence
from app.telemetry import record_call
from config.settings import Settings
from app.providers.search.arxiv_provider import ArxivSearchProvider
from app.providers.search.semantic_scholar_provider import SemanticScholarProvider

logger = logging.getLogger(__name__)

MIN_CONFIDENCE_FOR_VERDICT = 0.75
_FALLBACK_REASON = "Automated fact-check could not produce a confident result; requires manual review."
_QUOTA_REASON = "Web search verification unavailable (grounding quota exhausted for this account); requires manual review."
FACT_CHECK_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["supported", "contradicted", "unclear"]},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["status", "confidence", "reason"],
}


def quota_fallback(claim: Claim) -> ClaimVerification:
    return ClaimVerification(
        claim_id=claim.claim_id,
        status="unclear",
        confidence=0.0,
        reason=_QUOTA_REASON,
        evidence=[],
        verification_basis="plausibility_heuristic_only",
        verification_error="search_quota_exhausted",
    )


def _render_search_results(results: list[dict]) -> str:
    return "\n\n".join(
        f"Title: {result['title']}\nURL: {result['url']}\nSnippet: {result['content']}"
        for result in results
    )


from concurrent.futures import ThreadPoolExecutor


def _gather_sources(claim: Claim, settings: Settings) -> list[dict]:
    def _tavily() -> list[dict]:
        results = TavilySearchProvider(settings).search(claim.text, settings.tavily_max_results)
        for r in results:
            r.setdefault("source_type", "general_web")
        return results

    def _academic() -> list[dict]:
        if not getattr(settings, "enable_academic_search", True):
            return []
        return SemanticScholarProvider(settings).search(claim.text, settings.academic_max_results)

    with ThreadPoolExecutor(max_workers=2) as executor:
        tavily_future = executor.submit(_tavily)
        academic_future = executor.submit(_academic)
        return tavily_future.result() + academic_future.result()

def verify(
    claim: Claim,
    provider: ProviderAdapter,
    prompts: PromptRegistry,
    settings: Settings | None = None,
) -> ClaimVerification:
    # Keep direct callers on the historic Gemini-grounding behavior. The live
    # pipeline always passes its configured Settings instance explicitly.
    settings = settings or Settings(search_provider="gemini_grounding")
    use_tavily = settings.search_provider == "tavily"
    sources: list[dict] = []
    if use_tavily:
        sources = _gather_sources(claim, settings)
        if not sources:
            logger.warning("Tavily returned no evidence for claim %s", claim.claim_id)
            return quota_fallback(claim)
        rendered = prompts.render(
            "fact_check",
            version="v2",
            claim_text=claim.text,
            search_results=_render_search_results(sources),
        )
    else:
        rendered = prompts.render("fact_check", claim_text=claim.text)

    try:
        with record_call(
            "evidence_general",
            provider.name,
            provider.model_for_completion(use_grounding=not use_tavily),
            "fact_check.v2" if use_tavily else "fact_check.v1",
        ) as rec:
            result = provider.complete(
                prompt=rendered,
                response_schema=FACT_CHECK_RESPONSE_SCHEMA,
                use_grounding=not use_tavily,
            )
            rec.model_version = result.model_version
            rec.tokens_in, rec.tokens_out = result.tokens_in, result.tokens_out

        parsed = json.loads(result.text) if result.text else {}
        logger.debug("Fact-check response for claim %s: raw=%r parsed=%r", claim.claim_id, result.text, parsed)
        expected_keys = {"status", "confidence", "reason"}
        if not isinstance(parsed, dict) or not expected_keys.issubset(parsed):
            keys = list(parsed.keys()) if isinstance(parsed, dict) else []
            logger.warning(
                "Fact-check response missing expected keys for claim %s: got keys %s",
                claim.claim_id,
                keys,
            )
            parsed = {}
        status = parsed.get("status", "unclear")
        confidence = float(parsed.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))
        reason = (parsed.get("reason") or "").strip() or _FALLBACK_REASON
    except DailyQuotaExceeded:
        logger.warning("Grounding quota exhausted for claim %s - reporting as unclear with verification_error", claim.claim_id)
        return quota_fallback(claim)
    except Exception:
        logger.warning("Fact-check failed for claim %s - falling back to 'unclear'", claim.claim_id, exc_info=True)
        return ClaimVerification(
            claim_id=claim.claim_id,
            status="unclear",
            confidence=0.0,
            reason=_FALLBACK_REASON,
            evidence=[],
            verification_basis="plausibility_heuristic_only",
        )

    evidence_sources = sources if use_tavily else result.grounding_sources
    if status in ("supported", "contradicted") and (not evidence_sources or confidence < MIN_CONFIDENCE_FOR_VERDICT):
        reason = f"{reason} (downgraded to 'unclear': no verifiable grounding source or insufficient confidence)"
        status = "unclear"

    evidence: list[Evidence] = []
    verification_basis = "plausibility_heuristic_only"

    if status in ("supported", "contradicted") and evidence_sources:
        verification_basis = "external_source"
        for source in evidence_sources:
            url = source.get("url")
            if not url:
                continue
            evidence.append(Evidence(
                source_type=source.get("source_type", "general_web"),
                source_url=url,
                snippet=(source.get("content") or source.get("title") or reason)[:300],
            ))

    return ClaimVerification(
        claim_id=claim.claim_id,
        status=status,
        confidence=confidence,
        reason=reason,
        evidence=evidence,
        verification_basis=verification_basis,
    )


