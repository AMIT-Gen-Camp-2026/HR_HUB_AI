"""Severity assignment, issue/interview-question assembly (DETERMINISTIC), and
evidence-based correction generation (AI, contradicted-only) — docs/DECISIONS.md
section 7-8.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict

from app.prompts.registry import PromptRegistry
from app.providers.base import ProviderAdapter
from app.schemas.presentation import (
    Claim,
    ClaimVerification,
    Correction,
    InterviewQuestion,
    Issue,
)
from app.telemetry import record_call

logger = logging.getLogger(__name__)

_FALLBACK_CORRECTION = "No verified value was found in the available evidence."

_SEVERITY_TABLE: dict[tuple[str, str], str] = {
    ("contradicted", "high"): "critical",
    ("contradicted", "medium"): "high",
    ("contradicted", "low"): "medium",
    ("plausibility_flag", "high"): "high",
    ("plausibility_flag", "medium"): "medium",
    ("plausibility_flag", "low"): "low",
    ("unclear", "high"): "medium",
    ("unclear", "medium"): "low",
    ("unclear", "low"): "low",
}

# Regex to detect low-value version/environment strings
_VERSION_ENV_PATTERN = re.compile(
    r"(?:chrome|firefox|safari|edge|windows|ubuntu|linux|macos|ios|android)\s*\d+(?:\.\d+)*|"
    r"v\d+(?:\.\d+)+|version\s*\d+|desktop\s*browser|staging\s*vm",
    re.IGNORECASE,
)


def assign_severity(status: str, importance: str) -> str | None:
    return _SEVERITY_TABLE.get((status, importance))


def generate_correction(
    claim: Claim,
    verification: ClaimVerification,
    provider: ProviderAdapter,
    prompts: PromptRegistry,
) -> Correction | None:
    """Called ONLY for status == 'contradicted'. Builds a correction strictly from
    the attached evidence — never invents a fact not present in it."""
    if verification.status != "contradicted" or not verification.evidence:
        return None

    evidence = verification.evidence[0]
    rendered = prompts.render(
        "correction_generate",
        version="v1",
        claim_text=claim.text,
        evidence_text=evidence.snippet,
        source_url=evidence.source_url,
    )
    try:
        with record_call("correction_generate", provider.name, "", "correction_generate.v1") as rec:
            result = provider.complete(prompt=rendered, temperature=0.0)
            rec.model_version = result.model_version
            rec.tokens_in, rec.tokens_out = result.tokens_in, result.tokens_out
        text = (result.text or "").strip() or _FALLBACK_CORRECTION
    except Exception as exc:
        logger.warning("Correction generation failed for claim %s: %s", claim.claim_id, exc)
        text = _FALLBACK_CORRECTION

    return Correction(claim_id=claim.claim_id, text=text)


def build_issues(
    claims: list[Claim],
    verifications: list[ClaimVerification],
    corrections: dict[str, str] | None = None,
) -> list[Issue]:
    corrections = corrections or {}
    claim_by_id = {c.claim_id: c for c in claims}
    issues: list[Issue] = []

    for verification in verifications:
        claim = claim_by_id.get(verification.claim_id)
        if claim is None:
            continue
        severity = assign_severity(verification.status, claim.importance)
        if severity is None:
            continue
        issues.append(
            Issue(
                slide_number=claim.slide_number,
                claim_id=claim.claim_id,
                severity=severity,
                status=verification.status,
                claim_text=claim.text,
                correction=corrections.get(claim.claim_id),
            )
        )
    return issues


def _is_experience_claim(text: str) -> bool:
    lower = text.lower()
    return bool(
        re.search(r"\b(?:years|experience|defects?|bugs?|cycles?|sprints?|tickets?|logged|supported)\b", lower)
    )


def _is_low_value_logistics(claim: Claim) -> bool:
    """Filters out low-importance environment and version-only claims."""
    if claim.importance == "low":
        return True
    if claim.claim_type == "technology" and _VERSION_ENV_PATTERN.search(claim.text):
        return True
    return False


def _generate_candidate_questions(claim: Claim) -> list[tuple[str, str]]:
    """Returns a list of (template_key, formatted_question) tuples in order of preference."""
    text = claim.text

    if claim.claim_type == "business":
        return [
            ("biz_calc", f"How was the business/revenue impact in '{text}' calculated, and what baseline assumptions or transaction volumes were used?"),
            ("biz_model", f"What financial model or conversion assumptions underpin the projected benefit in '{text}'?"),
            ("biz_risk", f"What sensitivity analysis or downside scenarios did you evaluate for '{text}'?"),
        ]

    if claim.claim_type == "performance":
        if _is_experience_claim(text):
            return [
                ("perf_exp_ex", f"Can you give a specific example of a critical defect or challenge from '{text}' and walk through how you diagnosed it?"),
                ("perf_exp_breakdown", f"Can you break down the workflow and team collaboration involved in '{text}'?"),
                ("perf_exp_scale", f"How did your validation strategy in '{text}' scale across iterative product releases?"),
            ]
        return [
            ("perf_benchmark", f"What was the baseline benchmark and test workload profile used to evaluate '{text}'?"),
            ("perf_setup", f"Can you break down the experimental setup and validation data behind '{text}'?"),
            ("perf_repro", f"Under what edge conditions or concurrent workloads did you test '{text}'?"),
        ]

    if claim.claim_type == "capability":
        if _is_experience_claim(text):
            return [
                ("cap_exp_highlight", f"Can you highlight a pivotal testing milestone or quality breakthrough achieved in '{text}'?"),
                ("cap_exp_scale", f"How did your engineering approach to '{text}' evolve as project scale increased?"),
                ("cap_exp_process", f"What defect triage or root-cause framework did you implement for '{text}'?"),
            ]
        return [
            ("cap_edge_case", f"In the demo workflow for '{text}', what failure modes or edge cases did you encounter, and how did the system recover?"),
            ("cap_scale", f"How would the implementation of '{text}' adapt if the operational scale or user traffic increased significantly?"),
            ("cap_resilience", f"What regression safeguards were put in place to ensure ongoing stability for '{text}'?"),
        ]

    if claim.claim_type == "architecture":
        return [
            ("arch_tradeoff", f"What architectural trade-offs led to choosing '{text}' over alternative designs?"),
            ("arch_resilience", f"How does the architecture in '{text}' isolate component failures and maintain data consistency?"),
            ("arch_bottleneck", f"What potential performance bottlenecks were identified in '{text}' and how were they mitigated?"),
        ]

    if claim.claim_type == "dataset":
        return [
            ("data_quality", f"How did you ensure representative class distribution and guard against data quality issues in '{text}'?"),
            ("data_anomaly", f"What data validation and anomaly detection steps were applied to '{text}'?"),
            ("data_split", f"How were train/validation/test splits partitioned to prevent data leakage in '{text}'?"),
        ]

    if claim.claim_type == "algorithm":
        return [
            ("algo_constraints", f"What specific algorithmic constraints or performance criteria guided the design of '{text}'?"),
            ("algo_eval", f"How did you evaluate algorithmic convergence and edge-case behavior for '{text}'?"),
            ("algo_alt", f"What alternative algorithmic approaches were benchmarked before committing to '{text}'?"),
        ]

    # Technology
    return [
        ("tech_selection", f"What key criteria and technical constraints led to selecting '{text}' for this project?"),
        ("tech_integration", f"What technical challenges arose when integrating '{text}' into the broader stack?"),
        ("tech_security", f"What operational or security considerations influenced the deployment of '{text}'?"),
    ]


def build_interview_questions(
    claims: list[Claim],
    verifications: list[ClaimVerification],
) -> list[InterviewQuestion]:
    """Generates probing follow-up interview questions with deduplication and claim-type variation."""
    claim_by_id = {c.claim_id: c for c in claims}
    questions: list[InterviewQuestion] = []
    seen_claim_ids: set[str] = set()
    template_counts: dict[str, int] = defaultdict(int)

    # Priority 1: Flagged claims (must always be included)
    for verification in verifications:
        if verification.status == "plausibility_flag":
            claim = claim_by_id.get(verification.claim_id)
            if claim and claim.claim_id not in seen_claim_ids:
                seen_claim_ids.add(claim.claim_id)
                q = (
                    f"Can you walk me through how you arrived at: '{claim.text}'? "
                    f"({verification.reason})"
                )
                template_counts["flagged_anomaly"] += 1
                questions.append(
                    InterviewQuestion(
                        slide_number=claim.slide_number,
                        claim_id=claim.claim_id,
                        suggested_question=q,
                    )
                )

    # Priority 2: Filtered high and medium importance claims
    eligible_claims = [
        c for c in claims
        if c.claim_id not in seen_claim_ids and not _is_low_value_logistics(c)
    ]

    # Sort high importance first
    eligible_claims.sort(key=lambda c: 0 if c.importance == "high" else 1)

    for claim in eligible_claims:
        candidates = _generate_candidate_questions(claim)
        chosen_q: str | None = None
        chosen_key: str | None = None

        for tkey, qtext in candidates:
            # Check template key usage AND check sentence prefix usage
            prefix = qtext.split("'")[0]
            if template_counts[tkey] < 2 and template_counts[prefix] < 2:
                chosen_q = qtext
                chosen_key = tkey
                break

        if chosen_q and chosen_key:
            prefix = chosen_q.split("'")[0]
            seen_claim_ids.add(claim.claim_id)
            template_counts[chosen_key] += 1
            template_counts[prefix] += 1
            questions.append(
                InterviewQuestion(
                    slide_number=claim.slide_number,
                    claim_id=claim.claim_id,
                    suggested_question=chosen_q,
                )
            )

    # Fallback: if no questions generated yet but claims exist
    if not questions and claims:
        for claim in claims[:2]:
            if claim.claim_id not in seen_claim_ids:
                seen_claim_ids.add(claim.claim_id)
                candidates = _generate_candidate_questions(claim)
                qtext = candidates[0][1]
                questions.append(
                    InterviewQuestion(
                        slide_number=claim.slide_number,
                        claim_id=claim.claim_id,
                        suggested_question=qtext,
                    )
                )

    return questions