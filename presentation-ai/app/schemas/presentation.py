"""The output contract. This file IS the API — change it and you have changed the
contract every downstream consumer (HR tooling, future Demo AI integration) relies on.

Status values and the two-track claim model are fixed by docs/DECISIONS.md sections 3-4.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

# strip_whitespace=True means min_length is checked AFTER stripping — so a
# whitespace-only string ("   ") is correctly rejected, not just an empty string.
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

ClaimType = Literal[
    "performance", "dataset", "architecture", "technology",
    "algorithm", "capability", "business",
]

ClaimTrack = Literal["objective", "project_specific"]

Importance = Literal["high", "medium", "low"]

# See docs/DECISIONS.md section 4 — confirmed, final 6 status list.
ClaimStatus = Literal[
    "supported",             # track=objective or internal proof, confirmed
    "contradicted",          # track=objective or internal conflict, external evidence conflicts
    "project_unsupported",   # track=project_specific, self-reported / demo narrative claim, plausible but no external ground truth
    "plausibility_flag",     # track=project_specific, unusual value — needs human attention
    "unclear",                # either track, insufficient confidence to decide
    "not_checkable",          # not a verifiable factual claim at all
]

VerificationBasis = Literal[
    "internal_math_check",
    "external_source",
    "plausibility_heuristic_only",
    "not_applicable",
]

Severity = Literal["critical", "high", "medium", "low"]


class Evidence(BaseModel):
    """Attached for track=objective claims with web grounding or Track B claims with
    internal math verification."""

    source_type: Literal["official_documentation", "academic", "trusted_technical", "general_web"]
    source_url: str
    snippet: str = Field(description="Short excerpt or calculation rationale.")


class Claim(BaseModel):
    claim_id: str
    slide_number: int
    text: str
    claim_type: ClaimType
    track: ClaimTrack
    importance: Importance

    # canonical subject/property/value — see app/taxonomy/. Required for future
    # Presentation-vs-Demo comparison (docs/DECISIONS.md section 14).
    subject: str | None = None
    property: str | None = None
    value: float | str | None = None
    unit: str | None = None


class ClaimVerification(BaseModel):
    claim_id: str
    status: ClaimStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reason: NonEmptyStr = Field(
        description="MANDATORY, non-empty (whitespace-only also rejected). For "
        "plausibility_flag this is the human-readable justification shown to HR "
        "— never a bare boolean."
    )
    evidence: list[Evidence] = Field(default_factory=list)
    verification_basis: VerificationBasis = Field(
        default="plausibility_heuristic_only",
        description="Basis of verification: internal_math_check, external_source, "
        "plausibility_heuristic_only, or not_applicable.",
    )
    verification_error: str | None = Field(
        default=None,
        description="Non-fatal infrastructure/tool limitation error (e.g. 'search_quota_exhausted'). "
        "Separates system tool limitations from candidate content accuracy.",
    )


class Correction(BaseModel):
    """Track=objective only. NEVER invented — see app/pipeline/postprocess.py."""

    claim_id: str
    text: str


class Issue(BaseModel):
    slide_number: int
    claim_id: str
    severity: Severity
    status: ClaimStatus
    claim_text: str
    correction: str | None = None


class Scores(BaseModel):
    overall: int = Field(ge=0, le=100)
    fact_accuracy: int = Field(ge=0, le=100)
    verified_ratio: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Percentage of claims confirmed by concrete internal math checks or external ground sources.",
    )
    evidence_coverage: int = Field(ge=0, le=100)
    claim_reliability: int = Field(ge=0, le=100)


class Summary(BaseModel):
    total_claims: int
    supported: int = 0
    contradicted: int = 0
    project_unsupported: int = 0
    plausibility_flag: int = 0
    unclear: int = 0
    not_checkable: int = 0


class InterviewQuestion(BaseModel):
    """Suggested interview follow-up questions for HR/interviewer prep."""

    slide_number: int
    claim_id: str
    suggested_question: str


class PresentationMeta(BaseModel):
    filename: str
    slide_count: int


class CompletenessMeta(BaseModel):
    """Structured record of analysis completeness."""

    slides_total: int
    slides_processed: int
    slides_failed: int = 0
    status: Literal["ok", "partial", "no_extractable_content"] = "ok"
    message: str | None = None


class PresentationAnalysisResult(BaseModel):
    """Top-level response body for POST /api/v1/presentation/analyze."""

    analysis_id: str
    status: Literal["completed", "partial"] = "completed"
    completeness: CompletenessMeta
    presentation: PresentationMeta
    scores: Scores
    summary: Summary
    score_evidence: dict[str, str] | None = Field(
        default=None,
        description="Short, claim-grounded explanations for each displayed score.",
    )
    brief: str | None = Field(
        default=None,
        description="English-only presentation-level overview derived from slide content.",
    )
    claims: list[Claim] = Field(default_factory=list)
    verifications: list[ClaimVerification] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    suggested_interview_questions: list[InterviewQuestion] = Field(default_factory=list)
