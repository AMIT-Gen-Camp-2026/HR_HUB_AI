from unittest.mock import MagicMock

from app.pipeline.postprocess import build_interview_questions, generate_correction
from app.schemas.presentation import Claim, ClaimVerification, Evidence


def _claim(cid="C1", text="Prolog is a low-level language", importance="high", claim_type="technology"):
    return Claim(
        claim_id=cid, slide_number=1, text=text,
        claim_type=claim_type, track="objective", importance=importance,
    )


def test_generate_correction_skipped_unless_contradicted_with_evidence():
    provider = MagicMock()
    prompts = MagicMock()
    empty = ClaimVerification(claim_id="C1", status="contradicted", confidence=0.9, reason="wrong", evidence=[])
    supported = ClaimVerification(claim_id="C1", status="supported", confidence=0.9, reason="ok", evidence=[
        Evidence(source_type="general_web", source_url="https://example.com", snippet="x"),
    ])
    assert generate_correction(_claim(), empty, provider, prompts) is None
    assert generate_correction(_claim(), supported, provider, prompts) is None
    provider.complete.assert_not_called()


def test_generate_correction_calls_provider_when_contradicted_with_evidence():
    provider = MagicMock()
    provider.complete.return_value = MagicMock(text="Prolog is a high-level language.")
    prompts = MagicMock()
    prompts.render.return_value = "rendered"
    verification = ClaimVerification(
        claim_id="C1", status="contradicted", confidence=0.9, reason="docs disagree",
        evidence=[Evidence(source_type="general_web", source_url="https://example.com", snippet="high-level")],
    )
    result = generate_correction(_claim(), verification, provider, prompts)
    assert result is not None
    assert "high-level" in result.text
    provider.complete.assert_called_once()


def test_build_interview_questions_generates_distinct_phrasing_and_skips_low_value():
    claims = [
        # Business claim
        _claim("C1", text="$50 revenue impact per transaction", importance="high", claim_type="business"),
        # Performance / Experience claim
        _claim("C2", text="200+ defects logged and tracked to resolution", importance="high", claim_type="performance"),
        # Capability claim
        _claim("C3", text="Identified critical regression bug BUG-204 in checkout workflow", importance="high", claim_type="capability"),
        # Architecture claim
        _claim("C4", text="Bug located at Stage 4 payment gateway callback step", importance="medium", claim_type="architecture"),
        # Low importance / version claim (should be skipped)
        _claim("C5", text="Tested on Chrome 125.0 desktop browser environment", importance="low", claim_type="technology"),
        _claim("C6", text="Windows 11 staging VM", importance="medium", claim_type="technology"),
    ]
    verifications = [
        ClaimVerification(claim_id="C1", status="project_unsupported", confidence=0.95, reason="plausible"),
        ClaimVerification(claim_id="C2", status="project_unsupported", confidence=0.95, reason="plausible"),
        ClaimVerification(claim_id="C3", status="project_unsupported", confidence=0.95, reason="plausible"),
        ClaimVerification(claim_id="C4", status="project_unsupported", confidence=0.95, reason="plausible"),
        ClaimVerification(claim_id="C5", status="project_unsupported", confidence=0.95, reason="plausible"),
        ClaimVerification(claim_id="C6", status="project_unsupported", confidence=0.95, reason="plausible"),
    ]

    questions = build_interview_questions(claims, verifications)
    # C5 and C6 should be filtered out
    question_claim_ids = {q.claim_id for q in questions}
    assert "C5" not in question_claim_ids
    assert "C6" not in question_claim_ids

    # Questions should exist for C1, C2, C3, C4
    assert len(questions) == 4

    # Assert no two questions share an identical template string across 3+ distinct claim types
    templates = [q.suggested_question.split("'")[0] for q in questions]
    assert len(templates) == len(set(templates)), f"Duplicate templates detected: {templates}"
