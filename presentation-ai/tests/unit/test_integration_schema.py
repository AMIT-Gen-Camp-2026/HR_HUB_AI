"""Unit tests for finalized integration schemas (SpokenClaim, ClaimAlignment,
CrossModalSummary, CrossModalAnalysisResult).
"""
from typing import get_args
import pytest
from pydantic import ValidationError

from app.schemas.integration import (
    AlignmentRelationship,
    ClaimAlignment,
    CrossModalAnalysisResult,
    CrossModalStatus,
    CrossModalSummary,
    SpokenClaim,
)

_EXPECTED_RELATIONSHIPS = {
    "consistent",
    "contradicted",
    "additional",
    "missing",
    "unrelated",
}

_EXPECTED_STATUSES = {
    "completed",
    "partial",
    "failed",
}


# =============================================================================
# SpokenClaim Tests
# =============================================================================


def test_spoken_claim_minimal_valid():
    """A minimal valid SpokenClaim constructs and serializes correctly."""
    claim = SpokenClaim(
        spoken_claim_id="SPK-001",
        text="Our model achieved 94.2% accuracy.",
        start=10.5,
        end=14.0,
    )
    dumped = claim.model_dump()
    assert dumped["spoken_claim_id"] == "SPK-001"
    assert dumped["text"] == "Our model achieved 94.2% accuracy."
    assert dumped["start"] == 10.5
    assert dumped["end"] == 14.0
    assert dumped["claim_type"] is None
    assert dumped["source_segment_indices"] is None
    assert dumped["subject"] is None
    assert dumped["property"] is None
    assert dumped["value"] is None
    assert dumped["unit"] is None
    assert dumped["language"] is None

    # Round-trip validation
    reloaded = SpokenClaim.model_validate(dumped)
    assert reloaded == claim


def test_spoken_claim_full_fields():
    """SpokenClaim with all optional taxonomy and provenance fields."""
    claim = SpokenClaim(
        spoken_claim_id="SPK-002",
        text="We trained on 50,000 images with a latency of 12ms.",
        start=0.0,
        end=3.42,
        source_segment_indices=[0, 1],
        claim_type="performance",
        subject="model",
        property="latency",
        value=12.0,
        unit="ms",
        language="ar",
    )
    dumped = claim.model_dump()
    assert dumped["spoken_claim_id"] == "SPK-002"
    assert dumped["source_segment_indices"] == [0, 1]
    assert dumped["claim_type"] == "performance"
    assert dumped["property"] == "latency"
    assert dumped["value"] == 12.0
    assert dumped["unit"] == "ms"
    assert dumped["language"] == "ar"


def test_spoken_claim_end_before_start_raises():
    """end < start raises a validation error."""
    with pytest.raises(ValidationError) as exc_info:
        SpokenClaim(
            spoken_claim_id="SPK-003",
            text="Invalid timestamps claim.",
            start=15.0,
            end=10.0,
        )
    assert "end timestamp" in str(exc_info.value)


def test_spoken_claim_negative_timestamps_raise():
    """Negative start or end timestamps raise validation error."""
    with pytest.raises(ValidationError):
        SpokenClaim(
            spoken_claim_id="SPK-004",
            text="Negative start.",
            start=-1.0,
            end=5.0,
        )

    with pytest.raises(ValidationError):
        SpokenClaim(
            spoken_claim_id="SPK-005",
            text="Negative end.",
            start=0.0,
            end=-2.0,
        )


@pytest.mark.parametrize("invalid_text", ["", "   ", "\t\n  "])
def test_spoken_claim_empty_or_whitespace_text_raises(invalid_text):
    """Empty or whitespace-only text raises a validation error."""
    with pytest.raises(ValidationError):
        SpokenClaim(
            spoken_claim_id="SPK-006",
            text=invalid_text,
            start=0.0,
            end=1.0,
        )


def test_spoken_claim_excessive_length_raises():
    """Text exceeding maximum length (5000 chars) raises a validation error."""
    huge_text = "a" * 5001
    with pytest.raises(ValidationError):
        SpokenClaim(
            spoken_claim_id="SPK-007",
            text=huge_text,
            start=0.0,
            end=1.0,
        )


def test_spoken_claim_forbids_extra_fields():
    """Unexpected fields raise validation error."""
    with pytest.raises(ValidationError):
        SpokenClaim(
            spoken_claim_id="SPK-008",
            text="Valid text",
            start=0.0,
            end=1.0,
            unknown_extra_field="disallowed",  # type: ignore
        )


# =============================================================================
# ClaimAlignment Tests
# =============================================================================


def test_claim_alignment_valid():
    """Valid ClaimAlignment constructs and serializes correctly."""
    alignment = ClaimAlignment(
        presentation_claim_id="CLM-001",
        spoken_claim_id="SPK-001",
        relationship="consistent",
        confidence=0.95,
        reason="Both slide and spoken demo assert 94.2% accuracy on the test set.",
        evidence_quote="we achieved 94.2% accuracy on the test split",
        timestamp_start=12.0,
        timestamp_end=15.5,
    )
    dumped = alignment.model_dump()
    assert dumped["presentation_claim_id"] == "CLM-001"
    assert dumped["spoken_claim_id"] == "SPK-001"
    assert dumped["relationship"] == "consistent"
    assert dumped["confidence"] == 0.95
    assert dumped["evidence_quote"] == "we achieved 94.2% accuracy on the test split"
    assert dumped["timestamp_start"] == 12.0
    assert dumped["timestamp_end"] == 15.5


def test_claim_alignment_missing_relationship_null_spoken_id():
    """When relationship is 'missing', spoken_claim_id is None."""
    alignment = ClaimAlignment(
        presentation_claim_id="CLM-002",
        spoken_claim_id=None,
        relationship="missing",
        confidence=0.90,
        reason="High-importance accuracy claim on slide 3 was never mentioned in the demo.",
    )
    dumped = alignment.model_dump()
    assert dumped["spoken_claim_id"] is None
    assert dumped["relationship"] == "missing"


def test_claim_alignment_additional_relationship():
    """When relationship is 'additional', spoken claim has no presentation claim counterpart."""
    alignment = ClaimAlignment(
        presentation_claim_id="NONE",
        spoken_claim_id="SPK-005",
        relationship="additional",
        confidence=0.88,
        reason="Speaker asserted SOTA benchmark beat by 15% which was not present in the slides.",
        timestamp_start=45.0,
        timestamp_end=48.2,
    )
    dumped = alignment.model_dump()
    assert dumped["relationship"] == "additional"
    assert dumped["spoken_claim_id"] == "SPK-005"


@pytest.mark.parametrize("invalid_reason", ["", "   ", "\n\t  "])
def test_claim_alignment_empty_or_whitespace_reason_raises(invalid_reason):
    """An empty or whitespace-only reason raises a validation error."""
    with pytest.raises(ValidationError):
        ClaimAlignment(
            presentation_claim_id="CLM-001",
            spoken_claim_id="SPK-001",
            relationship="consistent",
            confidence=0.9,
            reason=invalid_reason,
        )


@pytest.mark.parametrize("invalid_rel", [
    "agreement",
    "contradiction",  # old noun form; vocabulary uses adjective 'contradicted'
    "modified",
    "omitted",
    "supported",
    "unsupported_spoken",
    "random_string",
])
def test_claim_alignment_invalid_relationship_raises(invalid_rel):
    """An invalid relationship not in the five allowed values raises a validation error."""
    with pytest.raises(ValidationError):
        ClaimAlignment(
            presentation_claim_id="CLM-001",
            spoken_claim_id="SPK-001",
            relationship=invalid_rel,  # type: ignore
            confidence=0.9,
            reason="Some valid explanation.",
        )


@pytest.mark.parametrize("invalid_conf", [-0.1, 1.01, -100.0, 2.0])
def test_claim_alignment_out_of_bounds_confidence_raises(invalid_conf):
    """Confidence outside [0.0, 1.0] raises a validation error."""
    with pytest.raises(ValidationError):
        ClaimAlignment(
            presentation_claim_id="CLM-001",
            spoken_claim_id="SPK-001",
            relationship="consistent",
            confidence=invalid_conf,
            reason="Valid explanation.",
        )


def test_claim_alignment_timestamp_end_before_start_raises():
    """timestamp_end < timestamp_start raises validation error."""
    with pytest.raises(ValidationError):
        ClaimAlignment(
            presentation_claim_id="CLM-001",
            spoken_claim_id="SPK-001",
            relationship="consistent",
            confidence=0.9,
            reason="Valid reason.",
            timestamp_start=10.0,
            timestamp_end=5.0,
        )


def test_claim_alignment_forbids_extra_fields():
    """Unexpected fields raise validation error."""
    with pytest.raises(ValidationError):
        ClaimAlignment(
            presentation_claim_id="CLM-001",
            spoken_claim_id="SPK-001",
            relationship="consistent",
            confidence=0.9,
            reason="Valid reason.",
            extra_field="disallowed",  # type: ignore
        )


# =============================================================================
# Vocabulary & Literals Tests
# =============================================================================


def test_relationship_vocabulary_matches_decisions_doc():
    """The 5 allowed relationship literals match docs/DECISIONS.md exactly."""
    assert set(get_args(AlignmentRelationship)) == _EXPECTED_RELATIONSHIPS


def test_cross_modal_status_literals():
    """CrossModalStatus matches expected completed/partial/failed values."""
    assert set(get_args(CrossModalStatus)) == _EXPECTED_STATUSES


# =============================================================================
# CrossModalAnalysisResult & CrossModalSummary Tests
# =============================================================================


def test_cross_modal_analysis_result_serialization_and_summary_consistency():
    """CrossModalAnalysisResult serializes correctly with mixed relationships,
    and its summary counts are consistent with alignments list.
    """
    alignments = [
        ClaimAlignment(
            presentation_claim_id="CLM-001",
            spoken_claim_id="SPK-001",
            relationship="consistent",
            confidence=0.95,
            reason="Slide accuracy 94.2% matches spoken 94.2%.",
            timestamp_start=10.0,
            timestamp_end=13.0,
        ),
        ClaimAlignment(
            presentation_claim_id="CLM-002",
            spoken_claim_id="SPK-002",
            relationship="contradicted",
            confidence=0.92,
            reason="Slide claims 120ms latency but spoken demo stated 12ms.",
            timestamp_start=25.0,
            timestamp_end=28.0,
        ),
        ClaimAlignment(
            presentation_claim_id="CLM-003",
            spoken_claim_id=None,
            relationship="missing",
            confidence=0.85,
            reason="High importance dataset size claim was never mentioned in the demo.",
        ),
        ClaimAlignment(
            presentation_claim_id="NONE",
            spoken_claim_id="SPK-004",
            relationship="additional",
            confidence=0.80,
            reason="Speaker asserted SOTA beat not present in the slides.",
            timestamp_start=50.0,
            timestamp_end=54.0,
        ),
        ClaimAlignment(
            presentation_claim_id="CLM-005",
            spoken_claim_id="SPK-005",
            relationship="unrelated",
            confidence=0.75,
            reason="Speaker mentioned unrelated infrastructure setup.",
        ),
    ]

    summary = CrossModalSummary(
        total_alignments=len(alignments),
        consistent=sum(1 for a in alignments if a.relationship == "consistent"),
        contradicted=sum(1 for a in alignments if a.relationship == "contradicted"),
        additional=sum(1 for a in alignments if a.relationship == "additional"),
        missing=sum(1 for a in alignments if a.relationship == "missing"),
        unrelated=sum(1 for a in alignments if a.relationship == "unrelated"),
    )

    result = CrossModalAnalysisResult(
        schema_version="1.0.0",
        status="completed",
        presentation_analysis_id="ANL-1234567890ab",
        video_reference="applicant_demo_video.mp4",
        alignments=alignments,
        summary=summary,
        overall_consistency_score=78,
    )

    dumped = result.model_dump()
    assert dumped["schema_version"] == "1.0.0"
    assert dumped["status"] == "completed"
    assert dumped["presentation_analysis_id"] == "ANL-1234567890ab"
    assert dumped["video_reference"] == "applicant_demo_video.mp4"
    assert len(dumped["alignments"]) == 5
    assert dumped["overall_consistency_score"] == 78

    # Summary counts consistency check
    assert dumped["summary"]["total_alignments"] == 5
    assert dumped["summary"]["consistent"] == 1
    assert dumped["summary"]["contradicted"] == 1
    assert dumped["summary"]["additional"] == 1
    assert dumped["summary"]["missing"] == 1
    assert dumped["summary"]["unrelated"] == 1

    # schema_version is present only at top-level
    assert "schema_version" in dumped
    assert "schema_version" not in dumped["alignments"][0]
    assert "schema_version" not in dumped["summary"]


@pytest.mark.parametrize("invalid_score", [-1, 101, -50, 150])
def test_cross_modal_analysis_result_invalid_score_raises(invalid_score):
    """overall_consistency_score outside [0, 100] raises validation error."""
    with pytest.raises(ValidationError):
        CrossModalAnalysisResult(
            status="completed",
            presentation_analysis_id="ANL-test",
            video_reference="demo.mp4",
            overall_consistency_score=invalid_score,
        )


def test_cross_modal_analysis_result_invalid_status_raises():
    """Invalid status raises validation error."""
    with pytest.raises(ValidationError):
        CrossModalAnalysisResult(
            status="unknown_status",  # type: ignore
            presentation_analysis_id="ANL-test",
            video_reference="demo.mp4",
            overall_consistency_score=90,
        )


def test_cross_modal_analysis_result_forbids_extra_fields():
    """Unexpected fields raise validation error."""
    with pytest.raises(ValidationError):
        CrossModalAnalysisResult(
            status="completed",
            presentation_analysis_id="ANL-test",
            video_reference="demo.mp4",
            overall_consistency_score=90,
            unexpected_field="disallowed",  # type: ignore
        )
