import json
from unittest.mock import MagicMock
from app.pipeline.plausibility import (
    check_internal_math_consistency,
    hard_rules,
    _contextual_judgment,
    verify,
    verify_batch,
)
from app.providers.base import CompletionResult
from app.schemas.presentation import Claim


def _claim(**overrides):
    base = dict(claim_id='CLM-1', slide_number=1, text='x', claim_type='performance',
                track='project_specific', importance='high')
    base.update(overrides)
    return Claim(**base)


def test_hard_rule_fires_on_high_percentage_metric():
    claim = _claim(property='accuracy', value=99.9, unit='%')
    result = hard_rules(claim)
    assert result is not None


def test_hard_rule_fires_on_high_0to1_metric():
    claim = _claim(property='f1_score', value=0.998, unit=None)
    result = hard_rules(claim)
    assert result is not None


def test_hard_rule_fires_on_high_r2_on_0to1_scale():
    claim = _claim(property='r2_score', value=0.997, unit=None)
    result = hard_rules(claim)
    assert result is not None


def test_hard_rule_does_not_fire_on_qualitative_claim_without_context():
    claim = _claim(claim_type='technology', text='We used PostgreSQL as our primary database.')
    result = hard_rules(claim)
    assert result is None, f'Should not flag qualitative claims: {result}'


def test_hard_rule_fires_on_performance_claim_missing_context():
    claim = _claim(claim_type='performance', subject=None, property=None)
    result = hard_rules(claim)
    assert result is not None


def test_internal_math_consistency_check_verified():
    claim = _claim(text="4 (16%) defects isolated")
    context = "Total: 25 defects logged across the test suite."
    result = check_internal_math_consistency(claim, context)
    assert result is not None
    is_ok, reason = result
    assert is_ok is True
    assert "4/25 = 16" in reason

    # Test through verify()
    ver = verify(claim, context, MagicMock(), MagicMock())
    assert ver.status == "supported"
    assert ver.confidence == 1.0
    assert ver.verification_basis == "internal_math_check"
    assert len(ver.evidence) == 1
    assert "4/25 = 16" in ver.evidence[0].snippet


def test_internal_math_consistency_check_inconsistent():
    claim = _claim(text="4 (50%) defects isolated")
    context = "Total: 25 defects logged across the test suite."
    result = check_internal_math_consistency(claim, context)
    assert result is not None
    is_ok, reason = result
    assert is_ok is False
    assert "inconsistency" in reason


def test_contextual_judgment_reports_unclear_on_provider_failure():
    bad_provider = MagicMock()
    bad_provider.complete.side_effect = RuntimeError('simulated failure')
    prompts = MagicMock()
    prompts.render.return_value = 'rendered'

    result = _contextual_judgment(_claim(), 'context', bad_provider, prompts)
    assert result.status == 'unclear'
    assert 'internal model error' in result.reason
    assert 'No specific plausibility concern' not in result.reason


def test_verify_uses_hard_rule_before_calling_provider():
    claim = _claim(property='accuracy', value=100, unit='%')
    never_called_provider = MagicMock()
    never_called_provider.complete.side_effect = AssertionError('should not be called')
    prompts = MagicMock()

    result = verify(claim, 'context', never_called_provider, prompts)
    assert result.status == 'plausibility_flag'
    assert result.confidence == 0.9


def test_verify_batch_success():
    c1 = _claim(claim_id='CLM-001', text='Claim 1', claim_type='technology')
    c2 = _claim(claim_id='CLM-002', text='Claim 2', claim_type='architecture')
    
    mock_provider = MagicMock()
    batch_response = [
        {"claim_id": "CLM-001", "flagged": False, "reason": "Plausible tech", "confidence": 0.8},
        {"claim_id": "CLM-002", "flagged": True, "reason": "Suspicious arch", "confidence": 0.9},
    ]
    mock_provider.complete.return_value = CompletionResult(
        text=json.dumps(batch_response),
        model_version="test",
        tokens_in=100,
        tokens_out=50,
    )
    mock_prompts = MagicMock()
    mock_prompts.render.return_value = "rendered_batch_prompt"

    results = verify_batch([(c1, "ctx1"), (c2, "ctx2")], mock_provider, mock_prompts)
    assert len(results) == 2
    assert results[0].claim_id == "CLM-001"
    assert results[0].status == "project_unsupported"
    assert results[0].verification_basis == "plausibility_heuristic_only"
    assert results[1].claim_id == "CLM-002"
    assert results[1].status == "plausibility_flag"
    assert mock_provider.complete.call_count == 1


def test_verify_batch_falls_back_to_individual_on_malformed_batch():
    c1 = _claim(claim_id='CLM-001', text='Claim 1', claim_type='technology')
    c2 = _claim(claim_id='CLM-002', text='Claim 2', claim_type='architecture')

    mock_provider = MagicMock()
    # First call (batch) returns malformed JSON missing CLM-002
    malformed_batch = [{"claim_id": "CLM-001", "flagged": False, "reason": "ok"}]
    single_ok = {"flagged": False, "reason": "individual ok", "confidence": 0.7}
    
    mock_provider.complete.side_effect = [
        CompletionResult(text=json.dumps(malformed_batch), model_version="test"),
        CompletionResult(text=json.dumps(single_ok), model_version="test"),
        CompletionResult(text=json.dumps(single_ok), model_version="test"),
    ]
    mock_prompts = MagicMock()

    results = verify_batch([(c1, "ctx1"), (c2, "ctx2")], mock_provider, mock_prompts)
    assert len(results) == 2
    assert results[0].claim_id == "CLM-001"
    assert results[1].claim_id == "CLM-002"
    # 1 batch call + 2 fallback individual calls
    assert mock_provider.complete.call_count == 3
