# AMIT Instructor Hub — AI Service -- CV-Ranking

CV parsing, skill extraction, and candidate-to-JD ranking. Runs as its own container so
that its dependencies, its latency profile, and its failures stay isolated from the core API.

**Companion docs:** `docs/ARCHITECTURE.md` for the request path and system boundaries ·
`docs/FULLSTACK_INTEGRATION.md` for the current external API contract ·
`docs/DECISIONS.md` for the decision history and why certain choices exist.

## The rule that still holds

> A language model is used where language is the output. A score is computed by a documented algorithm, not generated.

The current ranking policy in `app/pipeline/ranking.py` is deterministic and does not call a model. The score is based on required-skill coverage plus a bounded preferred-skill bonus; semantic fit remains available as diagnostic metadata but has zero weight in the authoritative score.

Nothing in this service writes to an instructor record. Every output is a draft.

## Current runtime shape

One Flask app, one merged evaluation endpoint, one extraction provider, one optional embedding provider path.

| Piece | What it is |
| --- | --- |
| HTTP layer | Flask (`app/main.py`) |
| CV extraction | Hugging Face Inference Providers with `MODEL_CHAIN` fallback |
| Ranking | Deterministic hard-skill scoring; no model call in the scoring path |
| Embeddings | `semantic_fit()` remains available for diagnostics; it is not authoritative in the current score |
| PII handling | Email/phone/national-ID stripping before sending text to the model, then restored by regex extraction |

See `docs/FULLSTACK_INTEGRATION.md` for the current API contract and `docs/ARCHITECTURE.md` for the end-to-end request path.

## Quick start

```bash
git clone <repo-url>
cd ai-service
cp .env.example .env          # fill in HF_API_TOKEN and GEMINI_API_KEY if needed
python -m venv .venv
.venv/bin/pip install -e ".[dev,ui]"
make test                     # deterministic tests; no network needed
make run                      # Flask dev server on http://localhost:5000
make ui                       # Streamlit on http://localhost:8501
```

Docker:

```bash
docker compose up --build     # ai-service on :5000, ui on :8501
```

## Ranking summary

The current score is not the original `0.7 hard + 0.3 semantic` formula. The authoritative score is now based on:

- required-skill coverage ratio
- a bounded preferred-skill bonus
- a hard cap at `100.0`
- semantic fit disabled from the score by explicit configuration (`SEMANTIC_WEIGHT = 0.0`)

The exact formula and examples are documented in `docs/FULLSTACK_INTEGRATION.md` so integrators can build thresholds and UI states correctly.

## Architecture pointers

- Request path: `app/main.py` -> `app/pipeline/run.py` -> model validation / extraction -> `app/pipeline/ranking.py`
- Extraction status: `SUCCESS`, `EMPTY`, `FAILED`
- Supported external contract: `POST /api/v1/cv/evaluate`
- Rating and evidence fields are in `app/schemas/cv.py`
- Skill normalization and taxonomy recovery are in `app/skills/canonicalize.py`
- Embedding support remains in `app/providers/embeddings.py`, but it is not the authoritative score source under current policy.

## Rules the team agreed to (and their real status)

1. **No real CV is committed.** `data/` is gitignored.
2. **Every model output is validated against a Pydantic schema.** Yes; validation failures are retried across `MODEL_CHAIN` before surfacing a `502`.
3. **Every feature has a kill switch.** Ranking has `RANKING_ENABLED`; extraction does not yet have an equivalent kill switch.
4. **Evaluation data is required before trusting extraction quality.** This remains an open gap; the labelled extraction dataset is still empty.
5. **No docs should claim a score formula that is no longer in code.** This is the reason for the current documentation refresh.

## Where to start reading

| You are… | Read |
| --- | --- |
| New to the project | `docs/ARCHITECTURE.md`, then `app/pipeline/run.py` |
| Touching the prompt | `app/prompts/registry.py` |
| Touching embeddings | `app/providers/embeddings.py` and `scripts/check_embeddings.py` |
| Touching ranking | `app/pipeline/ranking.py` and `tests/unit/test_ranking.py` |
| Debugging extraction | `app/providers/hf_provider.py` and `app/pipeline/postprocess.py` |
| Integrating with the API | `docs/FULLSTACK_INTEGRATION.md` |
