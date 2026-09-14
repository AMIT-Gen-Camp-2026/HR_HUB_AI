from app.providers.api_provider import GeminiProvider
from config.settings import get_settings
import numpy as np

provider = GeminiProvider(get_settings())
vectors = provider.embed(['Our model achieved 96% accuracy.', 'Our CNN achieved 96 percent accuracy.', 'The weather is nice today.'])

print('Vector count:', len(vectors))
print('Vector dimension:', len(vectors[0]))

v1, v2, v3 = [np.array(v) for v in vectors]
sim_similar = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))
sim_different = np.dot(v1, v3) / (np.linalg.norm(v1) * np.linalg.norm(v3))

print(f'Similarity (similar claims): {sim_similar:.3f}')
print(f'Similarity (unrelated): {sim_different:.3f}')
print('PASS' if sim_similar > sim_different else 'FAIL')
