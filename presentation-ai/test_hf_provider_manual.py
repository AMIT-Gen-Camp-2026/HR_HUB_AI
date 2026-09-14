import time
from app.providers.hf_provider import HFProvider
from config.settings import Settings

provider = HFProvider(Settings(provider='hf'))

print('Loading model (first call, may take a while)...')
start = time.time()
vectors = provider.embed(['Our model achieved 96% accuracy.', 'Our CNN achieved 96 percent accuracy.', 'The weather is nice today.'])
elapsed = time.time() - start
print(f'Loaded and embedded in {elapsed:.1f}s')
print('Vector count:', len(vectors))
print('Vector dimension:', len(vectors[0]))

# Sanity check: semantically similar sentences should have higher cosine similarity
# than an unrelated sentence.
import numpy as np
v1, v2, v3 = [np.array(v) for v in vectors]
sim_similar = np.dot(v1, v2)   # both about 96% accuracy
sim_different = np.dot(v1, v3)  # accuracy claim vs weather

print(f'Similarity (similar claims): {sim_similar:.3f}')
print(f'Similarity (unrelated): {sim_different:.3f}')
print('PASS' if sim_similar > sim_different else 'FAIL — similar claims should score higher')

# Second call should be fast (model already cached in memory)
start2 = time.time()
provider.embed(['another quick test'])
print(f'Second call took {time.time() - start2:.2f}s (should be much faster)')
