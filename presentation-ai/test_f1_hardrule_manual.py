from app.pipeline.plausibility import hard_rules
from app.schemas.presentation import Claim

claim = Claim(claim_id='CLM-1', slide_number=1, text='F1 score of 0.998', claim_type='performance',
              track='project_specific', importance='high', property='f1_score', value=0.998, unit=None)
result = hard_rules(claim)
print('PASS' if result is not None else 'FAIL — f1_score hard rule still not firing')
print('reason:', result)
