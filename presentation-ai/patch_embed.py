path = 'app/providers/api_provider.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

old = '''    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError(
            "GeminiProvider does not provide embeddings - use PROVIDER=hf for embed() calls."
        )'''

new = '''    def embed(self, texts: list[str]) -> list[list[float]]:
        # REVISED DECISION (docs/DECISIONS.md section 17): originally embeddings
        # were local-only (HF). Switched to Gemini's hosted embedding model after
        # the local setup proved impractical. Same quota-error handling pattern
        # as complete() above, for consistency.
        try:
            response = self._client.models.embed_content(
                model=self._settings.gemini_embedding_model,
                contents=texts,
            )
        except genai_errors.ClientError as exc:
            if getattr(exc, "code", None) == 429 or "RESOURCE_EXHAUSTED" in str(exc):
                raise DailyQuotaExceeded(
                    "Gemini free-tier daily/rate quota exceeded. Try again later or switch to a paid tier."
                ) from exc
            raise
        return [list(e.values) for e in response.embeddings]'''

if 'def embed' not in content:
    print('ERROR: embed method not found at all')
elif 'response.embeddings' in content:
    print('Already patched, skipping.')
elif old.replace(chr(10), '') in content.replace(chr(10), ''):
    # exact match failed possibly due to whitespace, try direct replace first
    content2 = content.replace(old, new)
    if content2 == content:
        print('ERROR: old block not found for exact replace - manual check needed')
    else:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content2)
        print('Inserted successfully (exact match).')
else:
    content2 = content.replace(old, new)
    if content2 == content:
        print('ERROR: old block not found for exact replace - manual check needed')
    else:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content2)
        print('Inserted successfully.')
