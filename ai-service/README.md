# AMIT Instructor Hub — AI Service -- CV-Ranking

CV parsing, skill extraction, and candidate-to-JD ranking. Runs as its own container so
that its dependencies, its latency profile and its failures stay isolated from the core API.

**Companion doc:** `docs/ARCHITECTURE.md` for the request path in detail ·
`docs/DECISIONS.md` for why things are the way they are (including what changed and why,
dated).

---

## The one rule

> A language model is used where **language** is the output.
> A **score** is computed by a documented algorithm, not generated.

This holds in practice: `app/pipeline/ranking.py` (the score) is 100% deterministic —
skill matching + cosine similarity, no LLM call. The LLM is only used for one thing:
extracting structured fields from raw CV text.

Nothing in this service writes to an instructor record. Every output is a **draft**.

---

## What's actually running

One Flask app, one merged evaluation endpoint, one extraction provider, a choice of two embedding providers.

| Piece                                             | What it is                                                                                                                             |
| ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| HTTP layer                                        | Flask (`app/main.py`) — not FastAPI                                                                                                    |
| CV extraction                                     | Hugging Face Inference Providers, 2-model fallback chain (`MODEL_CHAIN`)                                                               |
| Ranking                                           | Deterministic algorithm, no model call                                                                                                 |
| Embeddings (used by ranking's semantic-fit score) | `local` (sentence-transformers) or `api` (OpenAI-compatible endpoint — Gemini by default)                                              |
| PII handling                                      | Email/phone/national-ID stripped before the CV text reaches the model provider; email/phone still populated via local regex extraction |

See `docs/ARCHITECTURE.md` for the full request path and `docs/DECISIONS.md` if you're
wondering why a design choice looks the way it does.

---

## Quick start

```bash
git clone <repo-url>
cd ai-service
cp .env.example .env          # fill in HF_API_TOKEN and GEMINI_API_KEY
python -m venv .venv
.venv/bin/pip install -e ".[dev,ui]"
make test                     # all mocked/deterministic - no network, no key needed
python -m scripts.check_embeddings   # needs a real GEMINI_API_KEY - confirms embeddings actually work
make run                      # Flask dev server on http://localhost:5000 (FLASK_PORT in .env)
make ui                       # Streamlit on http://localhost:8501
```

Docker:

```bash
docker compose up --build     # ai-service on :5000, ui on :8501
```

---

## Repository layout

```text
ai-service/
├── app/
│   ├── main.py                         Flask app - the only HTTP entry point (1 merged route)
│   ├── pipeline/                       extract → normalize → redact → prompt → model → validate
│   ├── prompts/                        one hand-written system prompt (registry.py)
│   ├── providers/                      hf_provider.py (extraction) + embeddings.py (local | api)
│   ├── schemas/                        Pydantic models — CVSchema, JobDescription, RankingResult
│   └── security/                       file_validator.py — magic-byte checks, safe storage names
├── config/settings.py                  all env vars, one place
├── eval/                               labelled datasets + runners — dataset is currently empty, see below
├── ui/streamlit_app.py                 manual-testing tool, not the product
├── tests/                              unit + integration, all mocked (no network needed to run them)
├── scripts/                            one-off ops scripts (e.g. check_embeddings.py)
├── docs/                               architecture, decisions log
└── data/                               gitignored — never commit a real CV
```

---

## Rules the team agreed to (and their real status)

1. **Nothing in `notebooks/` is imported by `app/`.** ✅ true today.
2. **No secret in the repository, ever.** Keys come from `.env` (gitignored). No CI
   secret-scan is wired up yet.
3. **No real CV is committed.** `data/` is gitignored.
4. **Every model output is validated against a Pydantic schema.** ✅ `CVSchema(**data)` in
   `app/pipeline/run.py::parse_and_validate` — a validation failure is a hard error, retried
   against the next model in `MODEL_CHAIN`.
5. **Every AI call is logged.** Partially true — `logging` calls exist in `hf_provider.py`,
   but there's no structured cost/token/latency tracking. Aspirational beyond that.
6. **Every feature has a kill switch.** True for ranking (`RANKING_ENABLED`, tested). Not
   true for extraction yet.
7. **A feature without a metric cannot be accepted.** Not enforced —
   `eval/datasets/cv-extraction/v1/labels.jsonl` is currently empty, so extraction accuracy
   has not actually been measured. This is the single biggest gap before trusting the
   pipeline's real-world accuracy.

---

## Where to start reading

| You are…                   | Read                                                                                  |
| -------------------------- | ------------------------------------------------------------------------------------- |
| New to the project         | `docs/ARCHITECTURE.md`, then `app/pipeline/run.py`                                    |
| Touching the prompt        | `app/prompts/registry.py` — read the security rules before editing                    |
| Touching embeddings        | `app/providers/embeddings.py`, then run `scripts/check_embeddings.py`                 |
| Touching ranking           | `app/pipeline/ranking.py` + `tests/unit/test_ranking.py`                              |
| Debugging a bad extraction | `app/providers/hf_provider.py` logs + `app/pipeline/postprocess.py`                   |
| Adding an evaluation       | `eval/README.md` — and consider that the dataset is empty, so this is high-value work |
