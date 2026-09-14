from app.providers.stub_provider import StubProvider
from config.settings import Settings
import json

provider = StubProvider(Settings(provider='stub'))

# Shape 1: claim extraction (array response_schema)
r1 = provider.complete(prompt='extract claims', response_schema={'type': 'array'})
parsed1 = json.loads(r1.text)
print('Test 1 (array):', 'PASS' if isinstance(parsed1, list) and len(parsed1) > 0 else 'FAIL')

# Shape 2: plausibility judgment (prompt contains 'flagged')
r2 = provider.complete(prompt='... return flagged: true/false ...')
parsed2 = json.loads(r2.text)
print('Test 2 (plausibility):', 'PASS' if 'flagged' in parsed2 else 'FAIL')

# Shape 3: fact check (prompt contains status)
r3 = provider.complete(prompt='return \"status\": \"supported\"')
parsed3 = json.loads(r3.text)
print('Test 3 (fact_check):', 'PASS' if 'status' in parsed3 else 'FAIL')

# Shape 4: correction (prompt contains 'neutral sentence') -> plain text, not JSON
r4 = provider.complete(prompt='Write ONE short, neutral sentence correcting it')
print('Test 4 (correction, plain text):', 'PASS' if r4.text == 'No verified value was found in the available evidence.' else 'FAIL')

# Grounding sources
r5 = provider.complete(prompt='x', use_grounding=True)
r6 = provider.complete(prompt='x', use_grounding=False)
print('Test 5 (grounding on):', 'PASS' if r5.grounding_sources else 'FAIL')
print('Test 6 (grounding off):', 'PASS' if not r6.grounding_sources else 'FAIL')

# Embeddings
vectors = provider.embed(['a', 'b', 'c'])
print('Test 7 (embed count):', 'PASS' if len(vectors) == 3 else 'FAIL')
