"""The response shape IS the API — this test guards against accidental breaking changes."""
from typing import get_args
import pytest
from pydantic import ValidationError

from app.schemas.presentation import (
    ClaimStatus,
    ClaimVerification,
    CompletenessMeta,
    PresentationAnalysisResult,
    PresentationMeta,
    Scores,
    Summary,
    VerificationBasis,
)

_EXPECTED_STATUSES = {
    "supported",
    "contradicted",
    "project_unsupported",
    "plausibility_flag",
    "unclear",
    "not_checkable",
}

_EXPECTED_BASES = {
    "internal_math_check",
    "external_source",
    "plausibility_heuristic_only",
    "not_applicable",
}


def test_minimal_valid_result_serializes():
    result = PresentationAnalysisResult(
        analysis_id="ANL-test",
        completeness=CompletenessMeta(slides_total=1, slides_processed=1, slides_failed=0),
        presentation=PresentationMeta(filename="x.pptx", slide_count=1),
        scores=Scores(
            overall=100,
            fact_accuracy=100,
            verified_ratio=100,
            evidence_coverage=100,
            claim_reliability=100,
        ),
        summary=Summary(total_claims=0),
    )
    dumped = result.model_dump()
    assert dumped["status"] == "completed"
    assert dumped["claims"] == []
    assert dumped["verifications"] == []
    assert dumped["scores"]["verified_ratio"] == 100
    assert dumped["completeness"]["slides_total"] == 1
    assert dumped["score_evidence"] is None
    assert dumped["brief"] is None


def test_report_fields_are_optional_and_serialize_when_supplied():
    result = PresentationAnalysisResult(
        analysis_id="ANL-report",
        completeness=CompletenessMeta(slides_total=1, slides_processed=1),
        presentation=PresentationMeta(filename="x.pptx", slide_count=1),
        scores=Scores(overall=50, fact_accuracy=50, verified_ratio=0, evidence_coverage=0, claim_reliability=50),
        summary=Summary(total_claims=0),
        score_evidence={
            "overall": "Overall is 50.",
            "fact_accuracy": "Fact Accuracy is 50.",
            "evidence_coverage": "Evidence Coverage is 0.",
            "reliability": "Reliability is 50.",
        },
        brief="This is a one-slide presentation about a technical topic.",
    )
    dumped = result.model_dump()
    assert dumped["score_evidence"]["overall"] == "Overall is 50."
    assert dumped["brief"].startswith("This is")


def test_claim_status_literal_matches_decisions_doc():
    assert set(get_args(ClaimStatus)) == _EXPECTED_STATUSES


def test_verification_basis_literal():
    assert set(get_args(VerificationBasis)) == _EXPECTED_BASES


@pytest.mark.parametrize("reason", ["", "   "])
def test_verification_reason_rejects_empty_or_whitespace(reason):
    with pytest.raises(ValidationError):
        ClaimVerification(claim_id="C1", status="unclear", confidence=0.0, reason=reason, evidence=[])
