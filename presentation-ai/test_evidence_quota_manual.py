from unittest.mock import MagicMock
from app.errors import DailyQuotaExceeded
from app.pipeline.evidence_general import verify
from app.schemas.presentation import Claim

bad_provider = MagicMock()
bad_provider.complete.side_effect = DailyQuotaExceeded('simulated quota exceeded')

claim = Claim(claim_id='CLM-1', slide_number=1, text='Prolog is a low-level language.', claim_type='technology', track='objective', importance='medium')
prompts = MagicMock()
prompts.render.return_value = 'rendered prompt'

try:
    verify(claim, bad_provider, prompts)
    print('FAIL — DailyQuotaExceeded was swallowed instead of propagating')
except DailyQuotaExceeded:
    print('PASS — DailyQuotaExceeded correctly propagated')
