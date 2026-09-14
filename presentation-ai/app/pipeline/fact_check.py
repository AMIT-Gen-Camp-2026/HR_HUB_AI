"""Dispatcher - routes each claim to Track A (evidence_general) or Track B
(plausibility) based on its track. Per-claim failures never abort the whole batch.

Uses batched plausibility checking for Track B to minimize token overhead and latency.
"""
from __future__ import annotations

from app.pipeline import evidence_general, plausibility
from app.prompts.registry import PromptRegistry
from app.providers.base import ProviderAdapter
from app.schemas.presentation import Claim, ClaimVerification
from config.settings import Settings


def verify_claims(
    claims: list[Claim],
    provider: ProviderAdapter,
    prompts: PromptRegistry,
    slide_context_by_number: dict[int, str],
    settings: Settings,
) -> list[ClaimVerification]:
    verifications_by_id: dict[str, ClaimVerification] = {}
    project_claims: list[tuple[Claim, str]] = []
    grounding_quota_exhausted = False

    for claim in claims:
        if claim.track == "objective":
            ver = (
                evidence_general.quota_fallback(claim)
                if grounding_quota_exhausted
                else evidence_general.verify(claim, provider, prompts, settings)
            )
            verifications_by_id[claim.claim_id] = ver
            grounding_quota_exhausted = (
                settings.search_provider != "tavily"
                and ver.verification_error == "search_quota_exhausted"
            )
        else:
            context = slide_context_by_number.get(claim.slide_number, "")
            project_claims.append((claim, context))

    if project_claims:
        batch_results = plausibility.verify_batch(project_claims, provider, prompts)
        for ver in batch_results:
            verifications_by_id[ver.claim_id] = ver

    return [verifications_by_id[c.claim_id] for c in claims if c.claim_id in verifications_by_id]
