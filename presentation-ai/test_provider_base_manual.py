from app.providers.base import ProviderAdapter, CompletionResult

# Test 1: an incomplete implementation must be rejected by Python itself
class IncompleteProvider(ProviderAdapter):
    name = 'incomplete'
    def complete(self, **kwargs):
        pass
    # embed() is missing on purpose

try:
    p = IncompleteProvider()
    print('BUG: incomplete provider was instantiated:', p)
except TypeError as e:
    print('OK: incomplete provider correctly rejected by Python')

# Test 2: a complete implementation works fine
class CompleteProvider(ProviderAdapter):
    name = 'complete'
    def complete(self, **kwargs):
        return CompletionResult(text='ok', model_version='test-0')
    def embed(self, texts):
        return [[0.0] for _ in texts]

p = CompleteProvider()
result = p.complete(prompt='hello')
print('OK: complete provider works:', result.text, result.model_version)
