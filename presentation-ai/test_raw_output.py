from app.providers.api_provider import GeminiProvider
from config.settings import get_settings

provider = GeminiProvider(get_settings())
result = provider.complete(prompt='Return a JSON array with one object: {\"text\": \"hello\"}. Return ONLY the JSON array, nothing else.', response_schema={'type': 'array'})
print('Raw model output:')
print(repr(result.text))
