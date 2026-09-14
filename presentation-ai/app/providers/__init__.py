"""Provider abstraction layer. Everything above this package (pipeline/, api/) talks
ONLY to the ProviderAdapter interface in base.py — never imports google-genai or
sentence-transformers directly. This is what makes swapping Gemini for a local model
a one-line config change instead of a rewrite (see docs/PROVIDERS.md)."""