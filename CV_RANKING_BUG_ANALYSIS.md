# CV Ranking Bug Analysis

## Executive Summary

This investigation traced the supported flow in `ai-service/app/main.py` from
`POST /api/v1/cv/evaluate` through PDF/DOCX text extraction, `clean_and_query()`,
schema validation, and `ranking.rank()`. The named `TC-001_Happy_Path_Near_Perfect_Match.pdf`
is not present in this workspace, so the reported values `23.3` and `31.6` cannot
be reproduced from the supplied reference input.

Several causes are confirmed from code. Ranking is not LLM-generated, but it is
not fully reproducible across environments because `rank()` calls an external or
local embedding provider. The score is `70%` hard-skill score plus `30%` semantic
fit. The taxonomy contains no AI-instructor skills, although unknown skills still
have a raw exact/substring fallback. Preferred skills are scored separately but
are not included in the public `matched_skills` field. There is no early-zero branch
in `rank()`; reported zero scores caused by extraction or provider behavior remain
unconfirmed.

The recommended fix is to make exact/canonical required and preferred matching the
authoritative deterministic score, keep semantic similarity secondary and bounded
or use it only as an explicitly optional signal, expand the taxonomy from verified
requirements, expose preferred matches, and represent extraction as `SUCCESS`,
`EMPTY`, or `FAILED` rather than collapsing operational states.

## System Behavior

### Actual execution path

`app/main.py::evaluate_cv()`:

```text
multipart file + JSON job_description
  -> validate extension and magic bytes
  -> extract_raw_text() [extract_text_pdf.py or extract_text_docx.py]
  -> clean_and_query() [pipeline/run.py]
       -> clean_cv_text()
       -> redact PII
       -> build_prompt()
       -> hf_provider.query_model()
            -> model chain: primary -> fallback -> primary retry
       -> extract_json_from_model_output()
       -> normalize_model_output()
       -> CVSchema validation
  -> JobDescription validation (JSON supplied by caller; no JD LLM extraction)
  -> ranking.rank()
       -> canonicalise candidate and JD skill names
       -> exact/canonical skill matching
       -> required/preferred ratios and hard-skill weighting
       -> semantic_fit() -> embed() -> cosine similarity
       -> deterministic arithmetic and rounded score
  -> JSON response
```

Relevant code: `app/main.py::evaluate_cv`, `app/pipeline/run.py::clean_and_query`,
`app/pipeline/run.py::parse_and_validate`, `app/pipeline/ranking.py::rank`, and
`app/providers/embeddings.py::semantic_fit`.

`min_experience_years` is accepted by `JobDescription` but is not used by
`ranking.rank()`; this is documented in `ai-service/docs/ARCHITECTURE.md`.

## Reference Test Case

The requested PDF is absent: a workspace search for `**/*TC-001*` returned no
files. Therefore the exact extracted CV, exact JD payload, matched/missing lists,
embedding value, and score breakdown for Ahmed Hassan are unavailable.

The supplied candidate facts are consistent with a near-perfect conceptual fit,
but they are not evidence of what the LLM actually returned in this repository.
Any conclusion about a specific missing Ahmed skill is therefore **UNCONFIRMED**.

## BUG_CV_001

### Observed Behavior

The reported near-perfect candidate receives approximately `23.3`. This exact
value is **UNCONFIRMED** because the reference PDF and live response are absent.

### Expected Behavior

A CV containing direct matches for nearly all required skills should receive a
high score, approximately `90-100`, subject to the documented scoring policy.

### Reproduction

The executable reproduction surface is `ai-service/app/pipeline/ranking.py::rank`.
With two exact required matches and `semantic_fit=0`, the current implementation
returns `70.0`; with the same inputs and `semantic_fit=1`, it returns `100.0`.
This was verified by a direct Python probe. Existing tests also pin this behavior
in `ai-service/tests/unit/test_ranking.py`.

### Execution Trace

```text
CV extraction -> CVSchema.skills/inferred_skills
JD JSON -> JobDescription.required_skills/nice_to_have_skills
-> canonicalise() plus raw exact/substring fallback
-> required_ratio and nice_ratio
-> hard_skill_score (required weight .8, preferred weight .2)
-> semantic_fit (30% of final score)
-> round((.7 * hard_skill_score + .3 * fit_clamped) * 100, 2)
```

### Root Cause

**Confirmed architectural cause:** `app/pipeline/ranking.py::rank()` gives
semantic similarity `SEMANTIC_WEIGHT = 0.3` and only gives exact/canonical skill
matching `HARD_SKILL_WEIGHT = 0.7`. Thus a perfect hard-skill match can score as
low as `70.0` when semantic fit is zero. A score near `23.3` would require both
incomplete hard matching and/or low semantic fit, but the exact contribution
cannot be calculated without the missing extraction and embedding outputs.

**Confirmed accuracy factor:** `app/skills/taxonomy.yaml` has data, frontend, QA,
security, and general engineering entries but no listed ChatGPT, Gemini, AI Studio,
Midjourney, Firefly, Runway, ElevenLabs, AI marketing, or teaching taxonomy entries.
Canonicalization therefore cannot map those names to IDs. The raw fallback can
still match identical or containing strings, but it does not provide controlled
aliases such as `Google Gemini` to `Gemini` or `AI Studio` to `Google AI Studio`.

**Extraction portion:** **UNCONFIRMED** for TC-001. `clean_and_query()` uses an
LLM and the prompt explicitly asks it to flatten categorized skills, but no saved
model output or fixture is available to prove which skills were extracted.

### Contributing Factors

- `semantic_fit()` embeds aggregate CV and JD text, not individual skills.
- The API default in `.env.example` uses the external `api` embedding provider;
  local configuration may instead use sentence-transformers.
- Embedding failures are caught by the endpoint's broad ranking exception and
  returned as HTTP 500, but no ranking outcome records the failure state.
- The result exposes only required matched/missing skills, hiding preferred matches.

### Impact

The weighting allows a model/provider artifact to depress an exact match by 30
points. Missing taxonomy coverage reduces auditability and can reduce matches if
the raw fallback is insufficient. This affects ranking accuracy, fairness,
reproducibility, provider portability, and debugging.

### Recommended Fix

Make deterministic required/preferred matching authoritative. Preserve the current
weight policy unless product requirements approve a change, but do not let an
unvalidated aggregate embedding override direct evidence. Add verified AI skills
and aliases to `taxonomy.yaml`; use exact aliases before any narrowly measured
fuzzy behavior. Make semantic fit optional, bounded, logged in the breakdown, and
secondary to hard evidence.

### Alternative Fixes

- Increase hard-skill weight to 1.0: simple and cheap, but removes semantic
  context and changes the existing contract.
- Keep the current formula and improve embeddings: preserves behavior, but remains
  provider-dependent and cannot repair extraction/taxonomy errors.
- Ask the LLM to calculate the score: may look semantically richer, but is costly,
  non-auditable, and violates deterministic ranking requirements.

### Why the Recommended Fix Is Better

It fixes the evidence path at its source, keeps arithmetic inspectable, requires no
additional LLM call, and lets semantic similarity add limited value without being
able to erase direct skill matches.

## BUG_CV_002

### Observed Behavior

The same CV/JD reportedly returns `23.3` and later `31.6`. The values themselves
are **UNCONFIRMED** without the reference input and response logs.

### Expected Behavior

The same CV, JD, configuration, taxonomy, model versions, and embedding provider
must yield the same ranking score.

### Reproduction

`rank()` itself has no LLM call and iterates input lists in order. Its external
inputs are `semantic_fit()` and the already extracted `CVSchema`. Repeated calls
with the same `CVSchema`, `JobDescription`, and patched semantic value are stable;
this is covered by the existing deterministic unit tests.

### Execution Trace and Root Cause

**Confirmed possible source:** `clean_and_query()` calls `build_prompt()`, and
`app/prompts/registry.py::build_prompt()` inserts `secrets.token_hex(6)` into the
prompt on every request. This is randomized prompt text. The extractor model is
called with `temperature=0.0` in `app/providers/hf_provider.py`, but temperature
zero does not guarantee identical hosted model output across providers or model
revisions. Different valid CVSchema outputs can therefore produce different
scores. The fallback chain can also select different models after a validation or
transport failure.

**Confirmed provider source:** `semantic_fit()` calls `embed()` and either a
local model or HTTP embedding API selected by `EMBEDDING_PROVIDER`. Provider/model
changes, API behavior, or changed aggregate text can change the score. The cache
is content-hash keyed and does not itself introduce randomness. API results are
sorted by `index`, which prevents response-order swapping.

**Not found:** no score LLM call, unordered set iteration affecting arithmetic,
random seed in ranking, or `except Exception: return 0` in the ranking path.

### Recommended Fix

Version and pin the extraction prompt/model/taxonomy and persist extraction output
when auditing a ranking. Remove randomized delimiters from the scoring-critical
prompt, or keep them only for a separately versioned security mode. Pin one
embedding provider/model for production, record its version, and make the final
score hard-skill deterministic with semantic fit optional or a bounded tie-breaker.

### Alternative Fixes

- Seed a provider/model: often unavailable or ineffective for hosted inference.
- Retry until outputs agree: expensive, increases latency, and still lacks a
  guarantee.
- Cache complete CV extraction: improves repeatability for repeated documents but
  requires cache invalidation and does not solve first-run variability.

## BUG_CV_003

### Observed Behavior

A required-skill-only candidate reportedly receives `0`. This is **UNCONFIRMED**
for the current implementation.

### Expected Behavior

Partial required matching should produce the required-match proportion, not a total
zero. For example, `18/20` is `0.9` for that component.

### Reproduction and Execution Trace

`rank()` computes `len(matched_required) / len(required)` in `_match_ratio()`, then
adds it to `weighted_sum`. There is no `if required_matches == 0: score = 0`
branch. Existing `test_missing_required_skill_lowers_score_and_is_reported` proves
that `2/3` required skills yields a positive score when semantic fit is zero.

### Root Cause

No current early-zero implementation was found. A zero can legitimately result
when there are no hard matches, no preferred matches, and semantic fit is zero.
An extraction failure does not currently become a valid zero: `query_model()` raises
`ModelInferenceError`, and `evaluate_cv()` returns HTTP `502`. A valid but empty
`CVSchema` can be scored, however, which confuses “empty successful extraction”
with a candidate having no evidence.

The reported `0` is therefore **UNCONFIRMED** and requires the actual CVSchema,
JD payload, semantic value, and HTTP response/logs to identify whether it came from
valid zero evidence, empty extraction, or code outside this repository.

### Recommended Fix

Add explicit extraction status/evidence metadata and reject or flag `EMPTY` and
`FAILED` before ranking. Keep valid partial matching proportional. Add regression
tests for `18/20`, empty successful extraction, and extraction failure.

## BUG_CV_004

### Observed Behavior

A preferred-only candidate reportedly receives `0`. This is **UNCONFIRMED**.

### Expected Behavior

Preferred matches should contribute positively when the configured scoring policy
assigns them positive weight.

### Reproduction and Execution Trace

`rank()` separately computes `nice_ratio`, adds `NICE_TO_HAVE_WEIGHT = 0.2`, and
normalizes by the active weight total. With required skills present but none
matched, all preferred skills matched, and semantic fit zero, the current formula
produces `14.0` (`0.7 * 0.2 * 100`), not zero. With no required skills at all,
preferred-only matching is normalized to `20.0` before semantic contribution.

### Root Cause

No early required-match zero branch was found. Preferred skills are stored in
`JobDescription.nice_to_have_skills`, normalized/matched separately, and included
in `hard_skill_score`. The public response does omit them from `matched_skills` and
`missing_skills`; only the `breakdown` contains their lists. This is a confirmed
observability defect, not proof of the reported zero.

The reported zero remains **UNCONFIRMED** and may reflect an upstream empty
extraction, a different caller, a semantic/provider failure outside the shown
result, or an older implementation.

### Recommended Fix

Expose required and preferred matched/missing lists as separate backward-compatible
fields or clearly extend `breakdown`, and add preferred-only score tests. Preserve
the existing positive preferred weight until product evidence justifies changing it.

## Cross-Bug Root Cause Analysis

The central issue is a boundary problem, not one bad `if` statement:

1. LLM extraction is probabilistic even with `temperature=0.0` and randomized
   prompt delimiters.
2. The taxonomy is incomplete for the stated AI Instructor domain.
3. Deterministic matching and nondeterministic/provider-dependent semantic scoring
   are combined in one final number.
4. Extraction status is not carried into the ranking contract.
5. Preferred match details are calculated but mostly hidden from the response.

These facts explain why the code can be internally deterministic for a fixed
`CVSchema` while the end-to-end score is not guaranteed reproducible.

## LLM Responsibility Analysis

1. **Extract CV skills:** yes, through `query_model()` and `parse_and_validate()`.
2. **Extract JD skills:** no. The endpoint parses caller-supplied JSON into
   `JobDescription`; the UI builds that JSON from text areas.
3. **Calculate score:** no. `rank()` calculates it.
4. **Determine matched skills:** no. `_match_against_candidate()` does.
5. **Determine missing skills:** no. `_match_against_candidate()` does.
6. **Influence final score:** indirectly, yes, because extracted CV fields affect
   matching and embedding text.
7. **Called more than once:** potentially. `query_model()` tries primary,
   fallback, and primary retry, but normally returns after the first valid result.
8. **Different outputs produce different scores:** yes.
9. **Temperature:** explicitly `0.0` in `_call_model()`; no seed is configured.
10. **Structured validation:** yes, JSON extraction, normalization, and Pydantic
    `CVSchema`; extra fields are silently ignored by `StrictModel`.
11. **Failure vs empty:** no explicit status. Model failure raises `502`, but a
    successful empty schema is indistinguishable from an empty candidate.

The LLM should remain responsible for literal CV fact extraction only. Schema
validation, canonicalization, matching, evidence checks, and numerical scoring
should remain deterministic code.

## Skill Normalization Analysis

`canonicalise()` lowercases and trims, checks exact names and aliases, then applies
RapidFuzz `WRatio` at threshold `92`. Current verified behavior is limited:

| Inputs | Current result |
|---|---|
| `ChatGPT`, `chatgpt`, `Chat GPT`, `Chat-GPT` | all unknown; raw fallback only matches exact/substring forms |
| `Gemini`, `Google Gemini` | unknown and not a declared alias |
| `Google AI Studio`, `AI Studio` | unknown and not a declared alias |
| `Prompt Engineering`, lowercase form | both unknown; raw lowercase fallback matches identical spelling |
| `Adobe Firefly`, `Firefly` | unknown; no declared vendor alias |

The system does handle casing/outer whitespace in raw fallback and declared aliases
such as `Scikit-learn`/`sklearn`. It does not consistently normalize punctuation,
vendor prefixes, or these AI-specific aliases. Fuzzy matching is risky here:
`WRatio` can merge unrelated names without a domain-reviewed alias map.

Recommended strategy: canonical IDs with explicit, reviewed aliases; normalize
Unicode whitespace, case, and punctuation only for lookup; deduplicate by canonical
ID; use fuzzy matching only for measured, approved candidates and never as a
blanket “AI” equivalence rule.

## Required vs Preferred Analysis

The distinction survives the schema and matching path as
`required_skills` versus `nice_to_have_skills`. `rank()` applies `.8` and `.2`
weights respectively, but normalizes over whichever fields are present. This
means a JD with no required list can still score preferred matches positively.

The distinction is weakened in the response because `RankingResult` has only
`matched_skills` and `missing_skills`, populated with required lists. Preferred
lists appear only under `breakdown`. Add explicit preferred fields in a compatible
response extension and document the active-weight normalization.

## Deterministic Scoring Analysis

Current formula:

```text
hard_skill_score = (.8 * required_ratio + .2 * nice_ratio) / active_weight_total
final_score = (.7 * hard_skill_score) + (.3 * max(0, semantic_fit))
score = round(final_score * 100, 2)
```

The arithmetic, list iteration, and canonical sets are deterministic for fixed
inputs. Cosine calculation is deterministic for fixed vectors, but vectors are
provider/model outputs. The current `.env.example` selects API embeddings while
`Settings` defaults to local embeddings, so deployment configuration affects scores.

Recommended policy: required and preferred exact/canonical matching should be the
primary score; semantic fit should be a documented secondary component or tie-break
with a fixed provider/model and a bounded influence. Do not claim end-to-end
reproducibility while allowing unpinned external embeddings to control 30%.

## Semantic Similarity Analysis

`semantic_fit()` embeds one aggregate CV profile and one aggregate JD string.
Skills are not embedded individually. Similarity can therefore reward related
language, but it can also be low for exact skill overlap or high for broad semantic
similarity without a required skill. It cannot alter matched/missing lists, but it
does alter the final score.

The API path uses `httpx`; the local path uses sentence-transformers. The API
response is sorted by embedding `index`, which is a confirmed fix for batch order
swapping and is documented in `docs/DECISIONS.md`. A permanent unit test for that
sorting is still noted as missing there.

Recommendation: retain semantic similarity only as secondary context for experience,
responsibilities, or tie-breaking. It should not overpower direct required-skill
evidence. Pin provider/model and add mocked deterministic tests.

## Error Handling Analysis

No ranking `except Exception: return 0` pattern was found. The endpoint catches
ranking exceptions and returns HTTP `500`; extraction model-chain failure returns
HTTP `502`. This correctly distinguishes operational failure at HTTP level, but
the ranking result has no extraction status and a valid empty CV can be scored.

Use an explicit status such as `SUCCESS`, `EMPTY`, and `FAILED` in an internal
extraction result. Keep failed extraction out of ranking and return a structured
error. Allow successful empty extraction to be represented and audited distinctly,
with a policy decision whether to return zero, “insufficient evidence,” or reject
ranking; never silently treat it as a genuine candidate zero.

## Proposed Solutions

1. Add a reviewed AI Instructor taxonomy section and aliases.
2. Introduce canonical skill lookup/deduplication with explicit alias tests.
3. Return required and preferred match lists separately.
4. Preserve extraction status and distinguish `EMPTY` from `FAILED`.
5. Make hard matching primary and semantic fit optional/secondary.
6. Pin and record extraction model, prompt version, taxonomy version, and embedding
   provider/model for auditability.
7. Add deterministic mocked embedding and repeated-run tests.

## Alternatives Considered

An LLM scoring pass is rejected because it increases cost and latency and makes the
number non-auditable. Blanket fuzzy matching is rejected because it can create
false positives and does not solve provider variability. Removing all semantics is
simple and fully deterministic but loses useful responsibility/experience context;
keeping it as a bounded secondary signal is a better balance.

## Recommended Solution

```text
CV file
  -> deterministic text extraction and redaction
  -> LLM literal structured extraction (temperature 0, versioned prompt)
  -> schema validation + extraction status
  -> canonical skill IDs and reviewed aliases
  -> deterministic required/preferred matching
  -> deterministic score from match ratios and configured weights
  -> optional bounded semantic context/tie-break using pinned embeddings
  -> response with separate required/preferred evidence
```

This solves the common cause of all four reports without hardcoding a candidate or
expected score. It also preserves the public endpoint and existing core schemas by
adding fields rather than renaming existing ones.

## Implementation Plan

### P0: correctness and reproducibility

- `app/pipeline/ranking.py::rank`: make the hard-match policy authoritative,
  explicitly bound semantic contribution, and preserve current weights unless
  approved. Add required/preferred result fields without removing old fields.
- `app/providers/embeddings.py`: pin/record provider and model configuration and
  add a permanent response-order test.
- `app/prompts/registry.py::build_prompt`: version the prompt; assess removing
  randomized delimiters from the scoring-critical extraction path while retaining
  redaction and injection defenses.

### P1: ranking accuracy

- `app/skills/taxonomy.yaml` and `app/skills/canonicalize.py`: add reviewed
  AI-domain canonical IDs and aliases for the actual JD vocabulary. Add tests for
  ChatGPT forms, Gemini forms, AI Studio forms, Prompt Engineering, and Firefly.
- `app/pipeline/ranking.py`: deduplicate canonical candidate skills and expose
  required/preferred matched/missing evidence.

### P2: robustness

- `app/pipeline/run.py` and `app/main.py`: introduce extraction status and keep
  failed extraction distinct from successful empty extraction.
- `app/schemas/cv.py`: extend response/internal result models compatibly; do not
  remove current fields.

### P3: optimization

- Cache validated extraction by document/configuration identity where policy allows.
- Use semantic embeddings for responsibility/experience similarity or tie-breaking
  rather than broad aggregate skill scoring.

## Regression Test Plan

Add focused tests in `ai-service/tests/unit/test_ranking.py`,
`test_canonicalize.py`, and a new `test_embeddings.py`:

1. Near-perfect match: verified fixture and policy-specific expected range.
2. Repeated identical CV/JD: identical score and breakdown.
3. Strong required match: positive high score.
4. Preferred-only match: positive score according to the configured `.2` weight.
5. No matching skills: zero only for valid zero evidence and zero semantic signal.
6. Partial required match: `18/20` produces proportional required ratio.
7. Case normalization: ChatGPT case variants match.
8. Alias normalization: verified Gemini aliases match.
9. Duplicate candidate skill: no score inflation.
10. Extraction failure: explicit failure, never a valid zero score.
11. Empty successful extraction: explicit empty state, distinct from failure.
12. Required/preferred separation: preferred-only evidence is visible and scored.
13. Embedding batch response reversed: sorting by `index` keeps CV/JD aligned.

The named PDF must be added to a controlled fixture set, or its extracted
`CVSchema` and JD JSON must be supplied, before the `90-100` assertion can be
validated without inventing candidate data.

## Cost and Performance Impact

The recommended design adds no LLM call. Canonical lookup and deterministic
matching are negligible CPU/memory cost. A single optional embedding call remains
the main latency and provider cost; disabling it for skills lowers cost and makes
scores reproducible. Prompt/model version logging adds negligible overhead.

Extraction remains one normal LLM call, with up to three attempts only on failure
under the current fallback chain. A cache can reduce repeated extraction cost but
requires privacy, invalidation, and configuration-version controls.

## Backward Compatibility

The existing endpoint, `CVSchema` fields, `JobDescription` fields, and current
`RankingResult` fields should remain. Add preferred-specific evidence and status
metadata as optional fields. Existing callers that read `matched_skills`,
`missing_skills`, and `score` continue to work, though their interpretation should
be documented. Changing score semantics or disabling semantic fit is a behavior
change and requires a versioned scoring configuration or release note, not an API
rename.

## Expected Results After Fix

- Exact required matches are not depressed by an uncontrolled aggregate embedding.
- Approved AI aliases match consistently without broad “AI” fuzzy equivalence.
- Partial required matches remain proportional and non-zero when evidence exists.
- Preferred-only candidates receive the configured positive preferred contribution.
- Failed and empty extraction are visible and cannot masquerade as genuine zeroes.
- Repeated runs with the same versioned inputs and configuration return the same score.

## Final Recommendation

1. **BUG_CV_001:** confirmed score architecture can make perfect hard matching
   score only `70`; the exact `23.3` cause and Ahmed’s extracted missing skills are
   unconfirmed because the PDF/output are absent. Incomplete AI taxonomy is a
   confirmed contributing factor.
2. **BUG_CV_002:** extraction output and external embeddings are potential confirmed
   nondeterministic boundaries; randomized prompt delimiters and fallback models
   make different valid extraction outputs possible. The reported values are
   unconfirmed without repeated logs.
3. **BUG_CV_003:** no early-zero bug exists in current `rank()`; partial matches
   are proportional. A zero caused by the named case is unconfirmed. Empty versus
   failed extraction is the confirmed robustness gap.
4. **BUG_CV_004:** preferred skills are positively weighted and do not trigger an
   early zero in current `rank()`. Preferred evidence is hidden from primary result
   fields; the reported zero is unconfirmed.
5. **Least-complexity fix:** reviewed canonical aliases plus explicit extraction
   status, separate preferred evidence, and deterministic hard-match-first scoring
   with bounded optional semantics.
6. **LLM:** literal CV extraction only, with schema validation and versioning.
7. **Deterministic code:** normalization, matching, evidence, weighting, and score.
8. **Semantic similarity:** retain as secondary context/tie-breaker, not primary
   skill evidence; pin the provider/model or disable it for the authoritative score.
9. **Required/preferred scoring:** preserve the current `.8/.2` policy initially,
   document active-weight normalization, and expose both components.
10. **Extraction states:** explicit `SUCCESS`, `EMPTY`, and `FAILED`.
11. **Reproducibility guarantee:** fixed validated inputs, versioned prompt/model/
    taxonomy/configuration, pinned embeddings, deterministic matching, and repeated
    regression tests.
12. **Proof:** implement the twelve regression tests above, including the supplied
    reference fixture once it is available.