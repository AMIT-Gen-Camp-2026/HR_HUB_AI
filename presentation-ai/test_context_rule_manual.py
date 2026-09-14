from app.pipeline.plausibility import hard_rules
from app.schemas.presentation import Claim

# A qualitative technology claim with no subject/property should NOT be flagged anymore
claim = Claim(claim_id='CLM-1', slide_number=1, text='We used PostgreSQL as our primary database.',
              claim_type='technology', track='project_specific', importance='medium')
result = hard_rules(claim)
print('PASS' if result is None else f'FAIL — still flagged: {result}')
