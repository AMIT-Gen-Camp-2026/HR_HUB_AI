from app.providers.factory import build_provider
from config.settings import Settings

# Test 1: stub provider builds fine (doesn't need api_provider.py etc. to exist yet)
p = build_provider(Settings(provider='stub'))
print('Test 1 (stub build):', 'PASS' if p.name == 'stub' else 'FAIL')

# Test 2: unknown provider raises a clear error
try:
    build_provider(Settings(provider='nonsense'))
    print('Test 2 (unknown provider):', 'FAIL — should have raised')
except Exception as e:
    print('Test 2 (unknown provider):', 'PASS —', type(e).__name__)
