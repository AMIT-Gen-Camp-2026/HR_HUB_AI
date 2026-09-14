"""Importance-weighted scoring. DETERMINISTIC, pure function — no provider call,
no side effects. Same inputs must always produce the same outputs.

Graduated status scoring (FIX 1):
- Score("supported")            = 1.00   # verified by math check or real external evidence
- Score("project_unsupported")  = 0.80   # plausible, but genuinely unverifiable (personal/demo claim)
- Score("plausibility_flag")    = 0.30   # numerically or contextually implausible
- Score("contradicted")         = 0.00   # verified false
- Score("unclear")              = 0.50   # ambiguous / unresolvable without error

Verification Basis & Verified Ratio (FIX 3):
- verified_ratio: percentage of claims confirmed by concrete internal math checks or external ground sources.

Evidence Coverage (FIX 4):
- Measures the percentage of claims with concrete backing evidence in verification.evidence.
  Returns 0 if every claim's evidence array is empty.
"""
from __future__ import annotations

from app.schemas.presentation import Claim, ClaimVerification, Scores

_IMPORTANCE_WEIGHT = {"high": 3, "medium": 2, "low": 1}

_STATUS_SCORE = {
    "supported": 1.00,
    "project_unsupported": 0.80,
    "unclear": 0.50,
    "plausibility_flag": 0.30,
    "contradicted": 0.00,
}


def _has_basis(claim: Claim, verification: ClaimVerification) -> bool:
    """A claim 'has a basis' if it's backed by concrete evidence in verification.evidence."""
    return bool(verification.evidence)


_ACADEMIC_EVIDENCE_MULTIPLIER = 1.5


def _basis_strength(verification: ClaimVerification) -> float:
    """0 = no evidence, 1.0 = general evidence, higher = academic evidence present."""
    if not verification.evidence:
        return 0.0
    if any(e.source_type == "academic" for e in verification.evidence):
        return _ACADEMIC_EVIDENCE_MULTIPLIER
    return 1.0


def compute_scores(claims: list[Claim], verifications: list[ClaimVerification]) -> Scores:
    verif_by_id = {v.claim_id: v for v in verifications}

    scoreable = [
        (c, verif_by_id[c.claim_id])
        for c in claims
        if c.claim_id in verif_by_id and verif_by_id[c.claim_id].status != "not_checkable"
    ]

    if not scoreable:
        return Scores(
            overall=100,
            fact_accuracy=100,
            verified_ratio=100,
            evidence_coverage=100,
            claim_reliability=100,
        )

    total_acc_weight = 0.0
    weighted_acc_score = 0.0
    total_coverage_weight = 0.0
    weighted_basis = 0.0

    eligible_claims_count = 0
    concrete_verified_count = 0

    for claim, verification in scoreable:
        weight = float(_IMPORTANCE_WEIGHT.get(claim.importance, 2))
        total_coverage_weight += weight

        weighted_basis += weight * _basis_strength(verification)

        # Exclude infrastructure/tool failures (e.g. search quota exhausted) from accuracy calculation
        if verification.verification_error is not None:
            continue

        eligible_claims_count += 1
        if verification.verification_basis in ("internal_math_check", "external_source"):
            concrete_verified_count += 1

        total_acc_weight += weight
        status = verification.status
        status_score = _STATUS_SCORE.get(status, 0.80)
        weighted_acc_score += weight * status_score

    if total_acc_weight > 0:
        fact_accuracy = round(100 * weighted_acc_score / total_acc_weight)
    else:
        fact_accuracy = 100

    if eligible_claims_count > 0:
        verified_ratio = round(100 * concrete_verified_count / eligible_claims_count)
    else:
        verified_ratio = 0

    if total_coverage_weight > 0:
        evidence_coverage = round(100 * weighted_basis / total_coverage_weight)
    else:
        evidence_coverage = 0

    # Claim reliability mirrors accuracy
    claim_reliability = fact_accuracy

    # Overall: 50% Accuracy, 25% Evidence Coverage, 25% Reliability
    overall = round(0.50 * fact_accuracy + 0.25 * evidence_coverage + 0.25 * claim_reliability)

    return Scores(
        overall=max(0, min(100, overall)),
        fact_accuracy=max(0, min(100, fact_accuracy)),
        verified_ratio=max(0, min(100, verified_ratio)),
        evidence_coverage=max(0, min(100, evidence_coverage)),
        claim_reliability=max(0, min(100, claim_reliability)),
    )