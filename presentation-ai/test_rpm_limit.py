from app.providers.api_provider import GeminiProvider
from config.settings import get_settings

provider = GeminiProvider(get_settings())

for i in range(4):
    print(f'--- Call {i+1} ---')
    try:
        result = provider.complete(
            prompt='Return a JSON array with one object: {\"text\": \"hello ' + str(i) + '\"}. Return ONLY the JSON array.',
            response_schema={'type': 'array'},
        )
        print('OK:', result.text[:50])
    except Exception as e:
        print('FAILED with:', repr(e))
        if e.__cause__:
            print('Original cause:', repr(e.__cause__))
