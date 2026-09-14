"""Integration contracts and shared schemas for cross-modal comparison
between Presentation Analysis and Video Demo Analysis.

This module defines the explicit Pydantic models for:
1. SpokenClaim: Spoken claims extracted from Demo AI's transcription output.
2. ClaimAlignment: Pairwise alignment between presentation claims and spoken claims.
3. CrossModalSummary: Relationship counts mirroring Presentation Summary pattern.
4. CrossModalAnalysisResult: Top-level joint analysis result contract.

NOTE: This is schema scaffolding for future cross-modal capability. It is not
wired into the live presentation-only pipeline or API routes.
"""
from __future__ import annotations

from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.presentation import ClaimType, NonEmptyStr

# Sane, generous maximum length for extracted spoken claim text to avoid resource exhaustion
SpokenClaimText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]

AlignmentRelationship = Literal[
    "consistent",    # Spoken claim corroborates presentation claim
    "contradicted",  # Spoken claim directly conflicts with presentation claim
    "additional",    # Spoken claim exists with no matching presentation claim (candidate said something new in demo)
    "missing",       # Presentation claim exists with no matching spoken claim (never mentioned in demo)
    "unrelated",     # Claims are mutually independent / unrelated in subject matter
]

CrossModalStatus = Literal["completed", "partial", "failed"]


class SpokenClaim(BaseModel):
    """Represents one claim extracted from a demo video's transcript.

    IMPORTANT: spoken_claim_id (e.g. 'SPK-001') is stable ONLY within a single
    video's analysis result. The same caveat applies to presentation Claim.claim_id.
    It is not a permanent cross-session identifier.
    """

    model_config = ConfigDict(extra="forbid")

    spoken_claim_id: str = Field(
        description="Stable ONLY within a single video analysis, e.g. 'SPK-001'."
    )
    text: SpokenClaimText = Field(
        description="The extracted spoken claim text, non-empty and bounded."
    )
    start: float = Field(
        ge=0.0,
        description="Start timestamp in seconds (>= 0.0)."
    )
    end: float = Field(
        ge=0.0,
        description="End timestamp in seconds (must be >= start)."
    )
    source_segment_indices: list[int] | None = Field(
        default=None,
        description="Optional traceability back to raw Demo AI segment indices merged to produce this claim."
    )
    claim_type: ClaimType | None = Field(
        default=None,
        description="Canonical claim type from app.schemas.presentation.ClaimType."
    )
    subject: str | None = Field(
        default=None,
        description="Canonical subject entity, e.g. 'model', 'dataset', 'PostgreSQL'."
    )
    property: str | None = Field(
        default=None,
        description="Canonical property from app.taxonomy (e.g. 'accuracy', 'latency')."
    )
    value: float | str | None = Field(
        default=None,
        description="Scalar numeric or normalized string value."
    )
    unit: str | None = Field(
        default=None,
        description="Normalized unit string (e.g. '%', 'ms', 'count')."
    )
    language: str | None = Field(
        default=None,
        description="ISO language code from Demo AI output (e.g. 'ar', 'en')."
    )

    @model_validator(mode="after")
    def validate_end_ge_start(self) -> SpokenClaim:
        if self.end < self.start:
            raise ValueError(
                f"end timestamp ({self.end}) must be greater than or equal to start timestamp ({self.start})"
            )
        return self


class ClaimAlignment(BaseModel):
    """Represents the comparison result between one presentation claim and one (or zero) matched spoken claim."""

    model_config = ConfigDict(extra="forbid")

    presentation_claim_id: str = Field(
        description="Referenced Presentation Claim ID (e.g. 'CLM-001')."
    )
    spoken_claim_id: str | None = Field(
        default=None,
        description="Referenced Spoken Claim ID (null when relationship is 'missing')."
    )
    relationship: AlignmentRelationship = Field(
        description="Alignment verdict: 'consistent', 'contradicted', 'additional', 'missing', or 'unrelated'."
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence score bounded between 0.0 and 1.0."
    )
    reason: NonEmptyStr = Field(
        description="MANDATORY non-empty explanation of the verdict (whitespace-only rejected)."
    )
    evidence_quote: str | None = Field(
        default=None,
        description="Short quote from the spoken transcript supporting the verdict, when applicable."
    )
    timestamp_start: float | None = Field(
        default=None,
        ge=0.0,
        description="Start timestamp in seconds from the matched spoken claim."
    )
    timestamp_end: float | None = Field(
        default=None,
        ge=0.0,
        description="End timestamp in seconds from the matched spoken claim."
    )

    @model_validator(mode="after")
    def validate_timestamps(self) -> ClaimAlignment:
        if (
            self.timestamp_start is not None
            and self.timestamp_end is not None
            and self.timestamp_end < self.timestamp_start
        ):
            raise ValueError(
                f"timestamp_end ({self.timestamp_end}) must be >= timestamp_start ({self.timestamp_start})"
            )
        return self


class CrossModalSummary(BaseModel):
    """Aggregated count of claim alignments by relationship type, mirroring the Presentation Summary pattern."""

    model_config = ConfigDict(extra="forbid")

    total_alignments: int = 0
    consistent: int = 0
    contradicted: int = 0
    additional: int = 0
    missing: int = 0
    unrelated: int = 0


class CrossModalAnalysisResult(BaseModel):
    """Top-level unified result combining Presentation Analysis and Demo AI Spoken Claim Analysis.

    Target shape for future cross-modal consistency engine.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="1.0.0",
        description="Schema contract version, e.g. '1.0.0'."
    )
    status: CrossModalStatus = Field(
        description="Status of cross-modal analysis: 'completed', 'partial', or 'failed'."
    )
    presentation_analysis_id: str = Field(
        description="References a PresentationAnalysisResult analysis_id."
    )
    video_reference: str = Field(
        description="Filename or identifier for the demo video."
    )
    alignments: list[ClaimAlignment] = Field(
        default_factory=list,
        description="List of pairwise claim alignments."
    )
    summary: CrossModalSummary = Field(
        default_factory=CrossModalSummary,
        description="Summary counts per relationship type."
    )
    overall_consistency_score: int = Field(
        ge=0,
        le=100,
        description="Deterministic aggregate consistency score (0-100)."
    )
