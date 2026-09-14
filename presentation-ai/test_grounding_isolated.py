from app.providers.api_provider import GeminiProvider
from config.settings import get_settings

provider = GeminiProvider(get_settings())

print('--- Testing WITHOUT grounding (already know this works) ---')
try:
    result = provider.complete(prompt='What is 2+2? Answer in one word.')
    print('OK:', result.text[:100])
except Exception as e:
    print('FAILED:', repr(e))

print()
print('--- Testing WITH grounding (use_grounding=True) ---')
try:
    result = provider.complete(prompt='Is Prolog a low-level or high-level programming language? Search to confirm.', use_grounding=True)
    print('OK:', result.text[:200])
    print('Grounding sources found:', len(result.grounding_sources))
except Exception as e:
    print('FAILED:', repr(e))
    if e.__cause__:
        print('Cause:', repr(e.__cause__))
