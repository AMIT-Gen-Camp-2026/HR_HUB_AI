# Architecture

> **This document describes the system that actually runs today**, verified against the
> code (not the original design). For the design that was planned but never shipped, and
> why, see `docs/DECISIONS.md` — entry "Reality check: the four-decisions above never
> shipped" (2026-08-28).

## Why the AI service is a separate container

1. **Its dependency tree is unrelated to the core API** — `pdfplumber`, `python-docx`,
   optionally `sentence-transformers`/`torch` if `EMBEDDING_PROVIDER=local`.
2. **Its latency profile is incompatible.** A core API request is milliseconds; a model
   call (extraction or embeddings) is seconds. Sharing a process ties up a worker.
3. **Its failure must be survivable.** `RANKING_ENABLED` is a real, tested kill switch
   (see `tests/integration/test_rank_endpoint.py::test_rank_respects_kill_switch`).
   Extraction has no kill switch yet — a real gap, not a documented one.

## The two request paths that actually exist

### 1. CV extraction — `POST /api/v1/cv/extract`

Flask route (app/main.py)

```text
│
├─ validate_extension()          .pdf / .docx only, by filename
│
├─ save to disk (uuid filename)  app/security/file_validator.py
│
├─ validate_file_content()       magic-byte check, not just the extension
│
├─ extract_raw_text()            pdfplumber (.pdf) / python-docx (.docx)
│
▼
clean_and_query()  — app/pipeline/run.py
│
├─ clean_cv_text()               unicode NFKC, strip control/bidi chars, cap length
│
├─ extract_contact_info()        regex email/phone from the CLEAN text, BEFORE redact
│
├─ redact()                      strip email/phone/national-ID/long-digit-runs
│
├─ build_prompt()                system prompt + randomized delimiters around CV text
│
├─ assert_clean()                refuses to send if any identifier slipped through
│
├─ query_model()                 HF Inference Providers, MODEL_CHAIN fallback (2 models)
│
├─ extract_json_from_model_output()   brace-counting parser, not regex
│
├─ normalize_model_output()      field aliasing (e.g. position → job_title)
│
├─ CVSchema(**data)              Pydantic validation, extra fields silently ignored
│
└─ overwrite personal_info.email/phone with the regex-extracted values
│
▼
{"success": true, "cv": {...}}   — a draft; nothing is persisted by this service
```

Model failure (bad JSON, schema mismatch, HTTP error) on the first model in `MODEL_CHAIN`
automatically retries the next one. Only if every model in the chain fails does the request
return `502 ModelInferenceError`.

### 2. Ranking — `POST /api/v1/rank`

```text
Flask route (app/main.py)
│
├─ RANKING_ENABLED check          off? return {"success": false, "error": "..."}  (200)
│
├─ CVSchema(**payload["candidate"])        usually the output of /cv/extract, as-is
│
├─ JobDescription(**payload["job_description"])
│
▼
rank()  — app/pipeline/ranking.py   (100% deterministic — no LLM call in this path)
│
├─ canonicalise() every skill name          app/skills/canonicalize.py + taxonomy.yaml
│                                           (exact taxonomy match, then fuzzy ≥92%)
│
├─ hard_skill_score = 0.8 × required_match_ratio + 0.2 × nice_to_have_match_ratio
│
├─ semantic_fit()                           app/providers/embeddings.py
│     cosine similarity between an embedded CV-profile string and JD string
│
└─ final_score = 0.7 × hard_skill_score + 0.3 × semantic_fit
│
▼
RankingResult{score, matched_skills, missing_skills, semantic_fit, breakdown}
```

`min_experience_years` on `JobDescription` is accepted but **not used** in scoring —
`Experience` has no structured start/end dates to compute years from. Known gap.

## Embeddings: two providers, one function

`app/providers/embeddings.py::semantic_fit()` is the only thing `ranking.py` calls. Behind
it, `EMBEDDING_PROVIDER` picks:

* `local` — `sentence-transformers` (`BAAI/bge-m3` by default), runs on CPU, no network.
* `api` (**current default**) — any OpenAI-compatible embeddings endpoint, called via
  `httpx` directly (not the `openai` SDK). Configured for Gemini's OpenAI-compatibility
  endpoint out of the box (`gemini-embedding-001`).

Results are cached in-process by content hash (`_CACHE`, a plain dict — not shared across
`gunicorn` workers, see `docs/DECISIONS.md`). Run `python -m scripts.check_embeddings` after
touching any `EMBEDDING_*` setting — it's the one check that catches "the API call succeeds
but returns numbers that don't actually encode meaning" (wrong model, wrong endpoint).

## What lives where (as it actually is)

| Concern             | Location                         | Reality check                                                                                                                        |
| ------------------- | -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| HTTP layer          | `app/main.py`                    | Flask, not FastAPI. Two routes total.                                                                                                |
| Extraction pipeline | `app/pipeline/`                  | `run.py` orchestrates; each step is one file                                                                                         |
| PII handling        | `app/pipeline/redact.py`         | Identifier-stripping only, not full anonymization                                                                                    |
| The output contract | `app/schemas/cv.py`              | `CVSchema`/`JobDescription`/`RankingResult`                                                                                          |
| Prompt              | `app/prompts/registry.py`        | One system prompt, hand-written, not templated/Jinja                                                                                 |
| Extraction provider | `app/providers/hf_provider.py`   | The only extraction provider. No `api`/`local`/`stub` switch.                                                                        |
| Embedding providers | `app/providers/embeddings.py`    | `local` or `api` — the one provider switch that's real                                                                               |
| Skill vocabulary    | `app/skills/taxonomy.yaml`       | Partial — some entries are guessed, not sourced from real job profiles                                                               |
| File safety         | `app/security/file_validator.py` | Magic-byte validation, uuid storage names                                                                                            |
| Numbers             | `eval/`                          | Scaffolding exists; `eval/datasets/cv-extraction/v1/labels.jsonl` is currently empty — no real accuracy measurement has been run yet |
| Experiments         | `notebooks/`                     | Not imported by `app/`                                                                                                               |

## Known architectural gaps (tracked, not yet fixed)

1. **No authentication** on either endpoint. Rate limiting is IP-based and in-memory only.
2. **No evidence trail** on `RankingResult.matched_skills` — a reviewer can't see *why* a
   skill was counted as matched without re-reading the CV.
3. **`eval/` has no real data yet** — extraction accuracy is currently unmeasured.
4. **Taxonomy coverage is partial** — anything not in `taxonomy.yaml` falls back to exact
   case-insensitive string matching only.
