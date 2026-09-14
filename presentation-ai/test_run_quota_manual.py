from unittest.mock import MagicMock, patch
from app.errors import DailyQuotaExceeded
from app.pipeline.run import run_presentation_analysis
from app.pipeline.extract_pptx import ExtractedPresentation, SlideContent, SlideElement

fake_extracted = ExtractedPresentation(slide_count=1, slides=[
    SlideContent(slide_number=1, title='Test', elements=[SlideElement(type='text', content='Some claim here.')])
])

bad_provider = MagicMock()
bad_provider.complete.side_effect = DailyQuotaExceeded('simulated quota exceeded')
prompts = MagicMock()
prompts.render.return_value = 'rendered prompt'
settings = MagicMock()

with patch('app.pipeline.run.extract_pptx.extract', return_value=fake_extracted):
    try:
        run_presentation_analysis(filename='x.pptx', content=b'fake', provider=bad_provider, prompts=prompts, settings=settings)
        print('FAIL — DailyQuotaExceeded was swallowed somewhere in run.py')
    except DailyQuotaExceeded:
        print('PASS — DailyQuotaExceeded correctly reaches the top unmodified')
    except Exception as e:
        print(f'FAIL — wrong exception type propagated: {type(e).__name__}: {e}')
