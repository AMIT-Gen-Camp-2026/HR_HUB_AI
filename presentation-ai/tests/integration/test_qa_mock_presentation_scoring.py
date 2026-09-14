"""Integration test verifying FIX 1 through FIX 6 on the Software QA Tester Presentation fixture."""
import json
from unittest.mock import MagicMock

from app.pipeline.plausibility import verify_batch
from app.pipeline.postprocess import build_interview_questions
from app.pipeline.scoring import compute_scores
from app.providers.base import CompletionResult
from app.schemas.presentation import Claim, ClaimVerification, Evidence, Summary


def _build_mock_qa_claims() -> list[Claim]:
    return [
        Claim(claim_id="CLM-001", slide_number=1, text="6+ years of QA experience across web and API testing", claim_type="capability", track="project_specific", importance="high"),
        Claim(claim_id="CLM-002", slide_number=1, text="200+ defects logged and tracked to resolution", claim_type="capability", track="project_specific", importance="medium"),
        Claim(claim_id="CLM-003", slide_number=1, text="30+ release cycles supported across agile sprints", claim_type="capability", track="project_specific", importance="medium"),
        Claim(claim_id="CLM-004", slide_number=2, text="Tested on Chrome 125.0 desktop browser environment", claim_type="technology", track="project_specific", importance="low"),
        Claim(claim_id="CLM-005", slide_number=2, text="Executed automated tests on Windows 11 staging VM", claim_type="technology", track="project_specific", importance="low"),
        Claim(claim_id="CLM-006", slide_number=3, text="Identified critical regression bug BUG-204 in checkout workflow", claim_type="capability", track="project_specific", importance="high"),
        Claim(claim_id="CLM-007", slide_number=3, text="Bug located at Stage 4 payment gateway callback step", claim_type="architecture", track="project_specific", importance="medium"),
        Claim(claim_id="CLM-008", slide_number=3, text="Bug repro rate is 100% under concurrent cart updates", claim_type="capability", track="project_specific", importance="medium"),
        # Internally consistent arithmetic claims (4/25 = 16%, 1/25 = 4%, 20/25 = 80%)
        Claim(claim_id="CLM-009", slide_number=4, text="4 (16%) defects isolated in checkout module out of 25 total", claim_type="dataset", track="project_specific", importance="high", subject="defects", property="count", value=4),
        Claim(claim_id="CLM-010", slide_number=4, text="1 (4%) awaiting test data out of 25 total logged bugs", claim_type="dataset", track="project_specific", importance="medium", subject="defects", property="count", value=1),
        Claim(claim_id="CLM-011", slide_number=4, text="20 (80%) functional verification test cases passed", claim_type="dataset", track="project_specific", importance="medium", subject="tests", property="count", value=20),
        Claim(claim_id="CLM-012", slide_number=5, text="Estimated $50 revenue impact per transaction prevented by hotfix", claim_type="business", track="project_specific", importance="high"),
        Claim(claim_id="CLM-013", slide_number=5, text="Reduced test cycle execution time by 35%", claim_type="capability", track="project_specific", importance="high"),
        Claim(claim_id="CLM-014", slide_number=5, text="Achieved 95% automated test coverage on core checkout path", claim_type="capability", track="project_specific", importance="high"),
        Claim(claim_id="CLM-015", slide_number=6, text="Established shift-left testing practice in sprint planning", claim_type="capability", track="project_specific", importance="medium"),
        Claim(claim_id="CLM-016", slide_number=6, text="Implemented boundary value analysis for discount input fields", claim_type="algorithm", track="project_specific", importance="medium"),
        Claim(claim_id="CLM-017", slide_number=6, text="Created standardized bug triage severity rubric for QA team", claim_type="capability", track="project_specific", importance="low"),
    ]


def test_fix1_and_fix6_pure_unsupported_scores_below_100():
    """FIX 1 & FIX 6: When only project_unsupported claims exist (no math verified claims),
    fact_accuracy is NOT 100 and lands at 80."""
    claims = _build_mock_qa_claims()
    verifications = [
        ClaimVerification(
            claim_id=c.claim_id,
            status="project_unsupported",
            confidence=0.95,
            reason="Plausible claim.",
            evidence=[],
            verification_basis="plausibility_heuristic_only",
        )
        for c in claims
    ]
    scores = compute_scores(claims, verifications)

    # Assert fact_accuracy is NOT 100 when only project_unsupported claims exist
    assert scores.fact_accuracy == 80
    assert scores.verified_ratio == 0
    # FIX 4: evidence_coverage is 0 when all evidence[] arrays are empty
    assert scores.evidence_coverage == 0


def test_fix2_and_fix6_math_claims_resolve_to_supported_and_raise_score():
    """FIX 2 & FIX 6: Arithmetic claims on slide 4 resolve to status='supported' with
    internal_math_check verification_basis, raise fact_accuracy, and update summary.supported."""
    claims = _build_mock_qa_claims()
    slide_contexts = {
        1: "QA Engineer profile: 6+ years experience, 200+ defects logged, 30+ release cycles.",
        2: "Environment: Chrome 125.0 desktop browser, Windows 11 staging VM.",
        3: "Demo: BUG-204 in checkout workflow, Stage 4 payment gateway callback, 100% repro rate.",
        4: "Defect Breakdown (Total: 25 defects): 4 isolated in checkout (16%), 1 awaiting test data (4%), 20 passed (80%).",
        5: "Business Impact: $50 revenue impact, 35% test cycle reduction, 95% automated test coverage.",
        6: "Process: shift-left testing, boundary value analysis, triage rubric.",
    }

    mock_provider = MagicMock()
    # Mock contextual response for non-math claims
    canned_non_math = [
        {"claim_id": c.claim_id, "flagged": False, "reason": "Plausible candidate claim.", "confidence": 0.9}
        for c in claims
    ]
    mock_provider.complete.return_value = CompletionResult(
        text=json.dumps(canned_non_math),
        model_version="test",
        tokens_in=50,
        tokens_out=50,
    )
    mock_prompts = MagicMock()
    mock_prompts.render.return_value = "rendered"

    claims_with_context = [(c, slide_contexts[c.slide_number]) for c in claims]
    verifications = verify_batch(claims_with_context, mock_provider, mock_prompts)

    verif_by_id = {v.claim_id: v for v in verifications}

    # FIX 2: Check CLM-009, CLM-010, CLM-011 resolve to status="supported"
    math_claims = ["CLM-009", "CLM-010", "CLM-011"]
    for cid in math_claims:
        v = verif_by_id[cid]
        assert v.status == "supported", f"Expected {cid} to be 'supported', got {v.status}"
        assert v.confidence == 1.0
        assert v.verification_basis == "internal_math_check"
        assert len(v.evidence) == 1
        assert "internal://math-consistency-check" in v.evidence[0].source_url

    # FIX 6: Summary.supported > 0
    summary = Summary(total_claims=len(claims))
    for v in verifications:
        if hasattr(summary, v.status):
            setattr(summary, v.status, getattr(summary, v.status) + 1)

    assert summary.supported == 3
    assert summary.project_unsupported == 14

    # FIX 6: Scores rise above pure 80 due to math-verified claims
    scores = compute_scores(claims, verifications)
    assert scores.fact_accuracy > 80
    assert scores.fact_accuracy == 84  # Graduated score with 3 supported claims
    assert scores.verified_ratio == round(100 * 3 / 17)  # 18%
    assert scores.evidence_coverage > 0  # Not 0 because math evidence exists


def test_fix5_interview_questions_targeting_and_deduplication():
    """FIX 5: High-value question generation with varied phrasing, filtering low logistics,
    and deduplication."""
    claims = _build_mock_qa_claims()
    verifications = [
        ClaimVerification(
            claim_id=c.claim_id,
            status="supported" if c.claim_id in ("CLM-009", "CLM-010", "CLM-011") else "project_unsupported",
            confidence=1.0 if c.claim_id in ("CLM-009", "CLM-010", "CLM-011") else 0.95,
            reason="Verified" if c.claim_id in ("CLM-009", "CLM-010", "CLM-011") else "Plausible",
        )
        for c in claims
    ]

    questions = build_interview_questions(claims, verifications)
    assert len(questions) >= 5

    # FIX 5a: Low-importance version/logistics claims (CLM-004, CLM-005, CLM-017) are excluded
    q_cids = {q.claim_id for q in questions}
    assert "CLM-004" not in q_cids  # Chrome 125
    assert "CLM-005" not in q_cids  # Windows 11
    assert "CLM-017" not in q_cids  # low importance rubric

    # FIX 5b: Concrete question for business claim CLM-012
    q_biz = next(q for q in questions if q.claim_id == "CLM-012")
    assert "revenue impact" in q_biz.suggested_question.lower() or "$50" in q_biz.suggested_question

    # FIX 5c: No template prefix used more than 2 times
    prefixes = [q.suggested_question.split("'")[0] for q in questions]
    from collections import Counter
    prefix_counts = Counter(prefixes)
    for pfx, count in prefix_counts.items():
        assert count <= 2, f"Template prefix '{pfx}' was used {count} times (max allowed: 2)"
