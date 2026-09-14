# Providers

## Why Gemini Flash (PROVIDER=api)

Chosen for the production pipeline: high throughput, cost efficiency, built-in structured output decoding constraints (`response_schema`), and a built-in Google Search grounding tool for Track-1 (objective claim) fact-checking.

**Free-tier privacy note (docs/DECISIONS.md §6):** inputs/outputs on the free tier may be used by Google to improve the model. Suitable for development with synthetic presentations. Before processing real applicant data in production, switch to a paid enterprise tier or Vertex AI (where data is not retained for training).

## Two-Layer Structured Output Validation

Structured output in `app/providers/api_provider.py` operates in two complementary layers:

1. **Provider-level schema constraint (`response_schema` via Gemini API SDK)**: Passed to `google.genai.types.GenerateContentConfig` to constrain token generation at the decoding layer. This eliminates syntax errors, missing top-level keys, and malformed JSON before the response reaches application code.
2. **Application-level Pydantic validation**: The parsed model output is validated against domain Pydantic models (e.g. `Claim`, `ClaimVerification`, `RawPlausibilityItem`). This layer enforces semantic business rules that API JSON schemas cannot express — such as non-empty stripped strings (`NonEmptyStr`), canonical property normalization, taxonomy lookups, and bounded confidence ranges.

## Embeddings (Gemini Hosted vs Local Hugging Face)

- **Default Hosted (`gemini-embedding-001`)**: High-dimensional multilingual embeddings hosted on Gemini, used for semantic alignment without local model download overhead.
- **Local Hugging Face (`PROVIDER=hf`)**: `intfloat/multilingual-e5-large` run locally via `sentence-transformers`: free, no rate limits, supports Arabic + English + mixed content, and keeps applicant text on-premise.

## Swapping Providers

Set `PROVIDER` in `.env` to `api | hf | local | stub`. See `app/providers/factory.py` — this is the single seam that needs to change to add a new backend.

## Process-Wide RPM Pacing & Telemetry

- **Monotonic Pacing Clock**: `wait_for_gemini_pacing()` in `api_provider.py` ensures a minimum configurable delay (`gemini_call_pacing_seconds`) between consecutive Gemini API requests process-wide, preventing burst 429 errors.
- **Token Accounting**: Every call records `tokens_in` and `tokens_out` directly from API `usage_metadata` into `app/telemetry.py`, enabling real-time cost calculation and evaluation telemetry.
