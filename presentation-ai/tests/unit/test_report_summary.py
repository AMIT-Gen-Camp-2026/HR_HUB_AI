from unittest.mock import MagicMock

from app.pipeline.extract_pptx import SlideContent, SlideElement
from app.pipeline.report_summary import build_score_evidence, generate_report_summary
from app.providers.base import CompletionResult
from app.schemas.presentation import Claim, ClaimVerification, Evidence, Scores


def _claim(claim_id: str, text: str, importance: str = "medium") -> Claim:
    return Claim(
        claim_id=claim_id, slide_number=1, text=text, claim_type="performance",
        track="objective", importance=importance,
    )


def _scores() -> Scores:
    return Scores(overall=63, fact_accuracy=75, verified_ratio=50, evidence_coverage=25, claim_reliability=75)


def test_score_evidence_reports_actual_verdict_and_evidence_counts():
    claims = [_claim("C1", "A claim"), _claim("C2", "Another claim")]
    verifications = [
        ClaimVerification(
            claim_id="C1", status="supported", confidence=0.9, reason="confirmed",
            evidence=[Evidence(source_type="general_web", source_url="https://example.com", snippet="source")],
        ),
        ClaimVerification(claim_id="C2", status="contradicted", confidence=0.9, reason="conflicted"),
    ]

    evidence = build_score_evidence(claims, verifications, _scores())

    assert "1 of 2" in evidence["fact_accuracy"]
    assert "1 of 2" in evidence["evidence_coverage"]
    assert "63" in evidence["overall"]


def test_score_evidence_follows_arabic_claim_language():
    claims = [_claim("C1", "حقق النموذج دقة 90٪")]
    verifications = [ClaimVerification(claim_id="C1", status="unclear", confidence=0.0, reason="غير مؤكد")]

    evidence = build_score_evidence(claims, verifications, _scores())

    assert "دقة الحقائق" in evidence["fact_accuracy"]
    assert "1" in evidence["evidence_coverage"]


def test_brief_is_english_for_arabic_slides():
    provider = MagicMock()
    provider.name = "stub"
    provider.complete.return_value = CompletionResult(
        text="This three-slide deck introduces a machine-learning project. It covers data, model results, and deployment. Its tone is technical and informative.",
        model_version="test",
    )
    prompts = MagicMock()
    prompts.render.return_value = "presentation overview slide_content_start"
    slides = [SlideContent(1, "مشروع تعلم آلي", [SlideElement("text", "البيانات والنموذج")])]

    _, brief = generate_report_summary([], [], _scores(), slides, provider, prompts)

    assert brief.startswith("This")
    assert "machine-learning project" in brief
    assert "مشروع تعلم آلي" in prompts.render.call_args.kwargs["slide_content"]
    assert provider.complete.call_args.kwargs["temperature"] == 0.0


def test_empty_claims_and_slides_have_safe_english_output():
    provider = MagicMock()
    prompts = MagicMock()

    evidence, brief = generate_report_summary([], [], _scores(), [], provider, prompts)

    assert set(evidence) == {"overall", "fact_accuracy", "evidence_coverage", "reliability"}
    assert "0 scoreable claim(s)" in evidence["overall"]
    assert brief.startswith("This is a 0-slide presentation")
    provider.complete.assert_not_called()
