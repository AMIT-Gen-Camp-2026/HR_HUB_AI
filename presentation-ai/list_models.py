from google import genai
from config.settings import get_settings

client = genai.Client(api_key=get_settings().gemini_api_key)

print('Available models that support generateContent:')
for model in client.models.list():
    actions = getattr(model, 'supported_actions', None) or []
    if 'generateContent' in actions:
        print(' -', model.name)
