from unittest.mock import MagicMock, patch
from app.errors import DailyQuotaExceeded
from app.pipeline.evidence_general import verify as evidence_verify
from app.pipeline.plausibility import _contextual_judgment
from app.pipeline.run import run_presentation_analysis
from app.pipeline.extract_pptx import ExtractedPresentation, SlideContent, SlideElement
from app.schemas.presentation import Claim


def _quota_provider():
    p = MagicMock()
    p.complete.side_effect = DailyQuotaExceeded('simulated')
    return p


def test_evidence_general_degrades_quota_error_to_unclear():
    claim = Claim(claim_id='C1', slide_number=1, text='x', claim_type='technology',
                  track='objective', importance='medium')
    prompts = MagicMock()
    prompts.render.return_value = 'rendered'
    result = evidence_verify(claim, _quota_provider(), prompts)
    assert result.status == 'unclear'
    assert 'grounding quota' in result.reason.lower()


def test_plausibility_propagates_quota_error():
    claim = Claim(claim_id='C1', slide_number=1, text='x', claim_type='performance',
                  track='project_specific', importance='medium')
    prompts = MagicMock()
    prompts.render.return_value = 'rendered'
    try:
        _contextual_judgment(claim, 'ctx', _quota_provider(), prompts)
        assert False, 'DailyQuotaExceeded was swallowed'
    except DailyQuotaExceeded:
        pass


def test_run_pipeline_completes_despite_track_a_quota_failure():
    fake_extracted = ExtractedPresentation(slide_count=1, slides=[
        SlideContent(slide_number=1, title='Test', elements=[SlideElement(type='text', content='Some claim.')])
    ])
    prompts = MagicMock()
    prompts.render.return_value = 'rendered'
    settings = MagicMock()
    settings.claim_batch_size = 5
    with patch('app.pipeline.run.extract_pptx.extract', return_value=fake_extracted), \
         patch('app.pipeline.run.claim_extraction.extract_claims', return_value=(
             [Claim(claim_id='C1', slide_number=1, text='x', claim_type='technology', track='objective', importance='medium')],
             []
         )):
        result = run_presentation_analysis(
            filename='x.pptx', content=b'fake',
            provider=_quota_provider(), prompts=prompts, settings=settings,
        )
        assert result.status == 'completed'
        assert result.verifications[0].status == 'unclear'