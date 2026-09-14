from config.settings import get_settings

s1 = get_settings()
s2 = get_settings()

print('provider:', s1.provider)
print('embedding_model:', s1.embedding_model)
print('api_port:', s1.api_port)
print('daily_request_cap:', s1.daily_request_cap)

# Must be the SAME instance every call (cached), not a new one
print('cached correctly (same instance):', s1 is s2)
