from app.main import create_app
import os
os.environ['PROVIDER'] = 'stub'

app = create_app()
client = app.test_client()

# Monkey-patch the pipeline to simulate a quota failure reaching the route
from unittest.mock import patch
from app.errors import DailyQuotaExceeded

with patch('app.api.routes_presentation.run_presentation_analysis', side_effect=DailyQuotaExceeded('simulated')):
    import io
    data = {'file': (io.BytesIO(b'fake pptx bytes'), 'test.pptx')}
    resp = client.post('/api/v1/presentation/analyze', data=data, content_type='multipart/form-data')
    print('HTTP status:', resp.status_code)
    print('Body:', resp.get_json())
