from unittest.mock import MagicMock
from app.pipeline.plausibility import _contextual_judgment
from app.schemas.presentation import Claim

# Simulate a provider that always fails
bad_provider = MagicMock()
bad_provider.complete.side_effect = RuntimeError('simulated network failure')

claim = Claim(claim_id='CLM-1', slide_number=1, text='x', claim_type='performance', track='project_specific', importance='high')
prompts = MagicMock()
prompts.render.return_value = 'rendered prompt'

result = _contextual_judgment(claim, 'context', bad_provider, prompts)
print('status on failure:', result.status)
print('PASS' if result.status == 'unclear' else 'FAIL — should be unclear, not project_unsupported')
