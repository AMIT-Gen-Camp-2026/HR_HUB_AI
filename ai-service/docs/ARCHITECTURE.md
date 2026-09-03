# Architecture

> This document describes the service as it actually runs today, verified against the code in `app/` and the current docs. The design history remains in `docs/DECISIONS.md`; this file is the current operational description.

## Why the AI service is a separate container

1. **Its dependency tree is unrelated to the core API** — `pdfplumber`, `python-docx`, optional embedding libraries, and the Hugging Face inference stack are not part of the core backend runtime.
2. **Its latency profile is incompatible.** A core API request is milliseconds; model extraction and embeddings are seconds.
3. **Its failure must be survivable.** Ranking has a tested kill switch (`RANKING_ENABLED`), and the extraction pipeline has a fallback model chain and a graceful `FAILED`/`EMPTY` status handling path.

## The request path that actually exists

### Unified evaluation — `POST /api/v1/cv/evaluate`

This is a single multipart request: the client uploads the CV file and a JSON `job_description`, and the service extracts the CV and optionally ranks it in the same request.

```text
app/main.py
  ├─ validate `file` and `job_description`
  ├─ validate file extension / contents
  ├─ extract raw text from .pdf or .docx
  └─ call clean_and_query()

app/pipeline/run.py::clean_and_query()
  ├─ clean_cv_text()
  ├─ build snapshot cache key from cleaned content + config + versions
  ├─ extract contact info before redaction
  ├─ redact() for PII stripping
  ├─ build_prompt() with randomized delimiter around text
  ├─ assert_clean() safety gate
  ├─ query_model() via Hugging Face Inference Providers with MODEL_CHAIN fallback
  ├─ parse_and_validate() -> CVSchema
  ├─ restore email/phone from regex extraction
  ├─ taxonomy recovery scan using exact taxonomy names/aliases
  ├─ cache valid extraction payload in process memory
  └─ if ranking enabled: rank(validated_cv, job_description)
```

The route returns:

- `200` with `success: true` for a valid extraction and optional ranking
- `400` for form/file validation problems
- `401` for invalid or missing `X-API-Key` when configured
- `422` for invalid JD shape or no extractable text
- `502` when the model chain fails
- `500` for unexpected internal errors

`min_experience_years` is accepted by `JobDescription` but is not used anywhere in the ranking code today.

## Extraction snapshot retention

`clean_and_query()` keeps validated extraction snapshots in process memory to avoid rerunning the model for the same cleaned content and configuration. The key includes:

- cleaned-content SHA-256
- prompt version
- schema version
- taxonomy version
- configured model chain

The cache is:

- LRU capped at 128 entries
- TTL of one hour
- process-local only
- revalidated as `CVSchema` before reuse
- not written to disk

This is a deliberate bounded retention of validated CV payloads in memory. It avoids repeated calls without introducing a new persistent cache service.

## Taxonomy recovery stage

Before returning the extracted CV, the pipeline performs a taxonomy scan over the same redacted text seen by the model. It looks for exact taxonomy names and aliases, then unions those recovered skills with the model output. This is recorded as `taxonomy_recovered_skills` in `extraction_metadata` and is the mechanism used to recover literal skill terms that the model omitted.

## Ranking formula shape

The authoritative current score is computed in `app/pipeline/ranking.py` as follows:

```text
R = matched_required / unique_required
P = matched_preferred / unique_preferred

if R is not None:
    H = R + (0.2 * P * (1 - R))
else:
    H = 0.2 * P

score = round(min(H, 1.0) * 100, 2)
```

The score is therefore:

- required-coverage first
- preferred evidence as a bounded bonus
- capped at 100
- zero semantic contribution under the current configuration (`SEMANTIC_WEIGHT = 0.0`)

The semantic helper remains in the code path for diagnostics and future product evaluation, but it does not change the authoritative score today.

## Embeddings: available, but not authoritative

`app/providers/embeddings.py::semantic_fit()` remains available for local or API embedding use, and it is cached by content hash. However, the ranking pipeline sets `SEMANTIC_WEIGHT = 0.0`, so the final `score` is not influenced by embedding similarity. The data is still useful for diagnostics and future product evaluation, but it is not part of the current scoring contract.

## What lives where (actual runtime)

| Concern | Location | Reality |
| --- | --- | --- |
| HTTP layer | `app/main.py` | Flask, single merged evaluation route |
| Extraction orchestration | `app/pipeline/run.py` | cleans, redacts, prompts, validates, snapshots, recovers taxonomy |
| Ranking logic | `app/pipeline/ranking.py` | deterministic required-preferred scoring |
| Output contract | `app/schemas/cv.py` | `CVSchema`, `JobDescription`, `RankingResult` |
| Prompting | `app/prompts/registry.py` | single hand-written system prompt and prompt builder |
| Model provider | `app/providers/hf_provider.py` | Hugging Face Inference Providers with fallback chain |
| Embedding provider | `app/providers/embeddings.py` | local or API path available, but non-authoritative in score |
| Skill vocabulary | `app/skills/taxonomy.yaml` | exact aliases + fuzzy fallback, with controlled taxonomy recovery |
| File safety | `app/security/file_validator.py` | magic-byte validation and safe temporary storage names |
| Evaluation dataset | `eval/` | still empty in the current repo state |

## Known architectural gaps and open items

1. **Extraction quality remains provider-dependent.** The service can produce valid but different extractions across runs because the upstream model output is not fully deterministic.
2. **`eval/` is still empty.** There is no labelled extraction-quality dataset yet, so real-world accuracy remains unmeasured.
3. **`min_experience_years` remains accepted but unused.** This is a product-policy gap, not a ranking implementation bug.
4. **JD quality is still user-input dependent.** Section headers and narrative sentences pasted verbatim become literal skill entries unless the caller sanitizes the JD before submit.
5. **Taxonomy coverage is finite.** The recovery scan is exact and bounded, and fuzzy matching remains a review point rather than a guaranteed semantic solution.

## Current product boundaries

- A query can produce a valid `SUCCESS` with a numeric `score` of `0.0` if the CV is non-empty but has no matching skill evidence.
- `EMPTY` is a valid, non-error result for an extracted-but-uninformative CV and returns `ranking: null`.
- The `taxonomy_recovered_skills` field exists to explain a skill is present in the document but not yet in the model output.
- The score is deterministic for a validated input, but upstream extraction remains variable and does not guarantee identical CV structure across identical provider runs.
