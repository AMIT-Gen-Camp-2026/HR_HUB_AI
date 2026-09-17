from app.schemas.presentation import Claim, ClaimVerification, Evidence
from app.pipeline.scoring import compute_scores


def _claim(cid, importance='high', claim_type='performance', track='objective'):
    return Claim(
        claim_id=cid, slide_number=1, text='x', claim_type=claim_type,
        track=track, importance=importance,
    )


def test_all_supported_gives_perfect_fact_accuracy():
    claims = [_claim('c1'), _claim('c2')]
    verifications = [
        ClaimVerification(
            claim_id='c1',
            status='supported',
            confidence=0.9,
            reason='ok',
            evidence=[Evidence(source_type='general_web', source_url='https://example.com', snippet='test')],
            verification_basis='external_source',
        ),
        ClaimVerification(
            claim_id='c2',
            status='supported',
            confidence=0.9,
            reason='ok',
            evidence=[Evidence(source_type='trusted_technical', source_url='internal://math', snippet='math')],
            verification_basis='internal_math_check',
        ),
    ]
    scores = compute_scores(claims, verifications)
    assert scores.fact_accuracy == 100
    assert scores.verified_ratio == 100
    assert scores.evidence_coverage == 100
    assert scores.overall == 100


def test_high_importance_contradiction_hurts_more_than_low_importance():
    claims = [_claim('c1', importance='high'), _claim('c2', importance='low')]
    verifications_high_wrong = [
        ClaimVerification(claim_id='c1', status='contradicted', confidence=0.9, reason='x', evidence=[]),
        ClaimVerification(claim_id='c2', status='supported', confidence=0.9, reason='x', evidence=[]),
    ]
    verifications_low_wrong = [
        ClaimVerification(claim_id='c1', status='supported', confidence=0.9, reason='x', evidence=[]),
        ClaimVerification(claim_id='c2', status='contradicted', confidence=0.9, reason='x', evidence=[]),
    ]
    scores_a = compute_scores(claims, verifications_high_wrong)
    scores_b = compute_scores(claims, verifications_low_wrong)
    assert scores_a.fact_accuracy < scores_b.fact_accuracy


def test_not_checkable_is_excluded_entirely():
    claims = [_claim('c1'), _claim('c2')]
    verifications = [
        ClaimVerification(claim_id='c1', status='supported', confidence=0.9, reason='ok', evidence=[]),
        ClaimVerification(claim_id='c2', status='not_checkable', confidence=0.0, reason='opinion', evidence=[]),
    ]
    scores = compute_scores(claims, verifications)
    assert scores.fact_accuracy == 100


def test_empty_scoreable_list_returns_zero():
    # PR_BUG_001: when all claims are not_checkable the scoreable list is empty.
    # The corrected behavior returns 0 across all scores (not 100) so that
    # image-only / no-content presentations are not falsely reported as perfect.
    claims = [_claim('c1')]
    verifications = [
        ClaimVerification(claim_id='c1', status='not_checkable', confidence=0.0, reason='opinion', evidence=[]),
    ]
    scores = compute_scores(claims, verifications)
    assert scores.overall == 0
    assert scores.verified_ratio == 0


def test_graduated_scoring_for_self_reported_and_math_claims():
    # 15 self-reported / demo claims (score 0.80) + 2 supported math claims (score 1.00)
    claims = [_claim(f'c{i}', importance='medium', track='project_specific') for i in range(1, 16)]
    claims.extend([
        _claim('c16', importance='high', track='project_specific'),
        _claim('c17', importance='high', track='project_specific'),
    ])
    
    verifications = [
        ClaimVerification(
            claim_id=f'c{i}',
            status='project_unsupported',
            confidence=0.95,
            reason='plausible self-report',
            verification_basis='plausibility_heuristic_only',
        )
        for i in range(1, 16)
    ]
    verifications.extend([
        ClaimVerification(
            claim_id='c16',
            status='supported',
            confidence=1.0,
            reason='math confirmed: 4/25 = 16%',
            evidence=[Evidence(source_type='trusted_technical', source_url='internal://math', snippet='4/25 = 16%')],
            verification_basis='internal_math_check',
        ),
        ClaimVerification(
            claim_id='c17',
            status='supported',
            confidence=1.0,
            reason='math confirmed: 1/25 = 4%',
            evidence=[Evidence(source_type='trusted_technical', source_url='internal://math', snippet='1/25 = 4%')],
            verification_basis='internal_math_check',
        ),
    ])

    scores = compute_scores(claims, verifications)
    # Graduated accuracy: (15*2*0.80 + 2*3*1.00) / (30 + 6) = (24 + 6)/36 = 30/36 = 83.33% -> 83
    assert scores.fact_accuracy == 83
    assert scores.verified_ratio == 12  # 2 of 17 claims confirmed by concrete math
    assert scores.evidence_coverage == 17  # 6/36 weighted basis


def test_infrastructure_quota_error_does_not_lower_fact_accuracy():
    claims = [_claim('c1', track='objective'), _claim('c2', track='objective')]
    verifications = [
        ClaimVerification(
            claim_id='c1',
            status='supported',
            confidence=0.9,
            reason='ok',
            evidence=[Evidence(source_type='general_web', source_url='https://example.com', snippet='ok')],
            verification_basis='external_source',
        ),
        ClaimVerification(
            claim_id='c2',
            status='unclear',
            confidence=0.0,
            reason='quota exhausted',
            verification_basis='plausibility_heuristic_only',
            verification_error='search_quota_exhausted',
        ),
    ]
    scores = compute_scores(claims, verifications)
    # c2 is excluded from accuracy denominator due to verification_error
    assert scores.fact_accuracy == 100
    assert scores.verified_ratio == 100  # 1 out of 1 eligible claim
