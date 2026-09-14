from app.providers.api_provider import GeminiProvider
from config.settings import get_settings

provider = GeminiProvider(get_settings())
try:
    provider.complete(prompt='test')
except Exception as e:
    print('Full error detail:')
    print(e.__cause__ if e.__cause__ else e)
