"""Pydantic schemas. Framework-agnostic on purpose — Flask serializes them via
`.model_dump()`, but nothing in here imports Flask, so these are reusable as-is if
the web layer ever changes."""

from app.schemas.presentation import (
    Claim,
    ClaimStatus,
    ClaimTrack,
    ClaimType,
    ClaimVerification,
    CompletenessMeta,
    Correction,
    Evidence,
    Importance,
    InterviewQuestion,
    Issue,
    PresentationAnalysisResult,
    PresentationMeta,
    Scores,
    Severity,
    Summary,
)
from app.schemas.integration import (
    AlignmentRelationship,
    ClaimAlignment,
    CrossModalAnalysisResult,
    CrossModalStatus,
    CrossModalSummary,
    SpokenClaim,
)

__all__ = [
    "Claim",
    "ClaimStatus",
    "ClaimTrack",
    "ClaimType",
    "ClaimVerification",
    "CompletenessMeta",
    "Correction",
    "Evidence",
    "Importance",
    "InterviewQuestion",
    "Issue",
    "PresentationAnalysisResult",
    "PresentationMeta",
    "Scores",
    "Severity",
    "Summary",
    "AlignmentRelationship",
    "ClaimAlignment",
    "CrossModalAnalysisResult",
    "CrossModalStatus",
    "CrossModalSummary",
    "SpokenClaim",
]
