# CV Ranking Bug Fix Report

## 1. Executive Summary

The second pass independently checked the prior report, repository, tests, runtime
path, normalization, model provider, embeddings, and error handling before editing
production code. The prior report's fixture claim was confirmed: an exhaustive
workspace search found no `TC-001_Happy_Path_Near_Perfect_Match.pdf` and no
corresponding AI Instructor JD artifact. Therefore real TC-001 extraction and
before/after scoring are **NOT REPRODUCED**.

The verified implementation defects were that semantic similarity controlled 30%
of the score despite being an external provider result, AI-domain aliases were
absent, preferred matches were hidden from primary response fields, and successful
empty extraction had no explicit status. The fix makes hard skill matching the
authoritative score, keeps semantic fit as reported context without making an
embedding call when disabled, adds reviewed AI aliases, exposes preferred evidence
additively, and reports `SUCCESS`, `EMPTY`, or `FAILED` extraction status.

## 2. Previous Report Validation

### Confirmed

- `app/main.py::evaluate_cv()` is the supported merged endpoint.
- CV extraction is LLM-based; JD skills are caller-supplied JSON.
- `rank()` performs matching and arithmetic; it does not call an LLM.
- The old formula used 70% hard matching and 30% semantic similarity.
- AI Instructor vocabulary was absent from `taxonomy.yaml`.
- Preferred skills were scored but only exposed in `breakdown`.
- `query_model()` has a primary/fallback/retry chain and temperature `0.0`.
- `build_prompt()` used `secrets.token_hex(6)` for a security delimiter.
- Embedding API responses are sorted by `index`.
- No early-zero branch or `except: return 0` was found in ranking.

### Partially Confirmed

- The architecture can produce a low score for a perfect hard match: exact
  matching with semantic fit `0` previously produced `70.0`. The exact reported
  `23.3` and `31.6` require the missing fixture, model outputs, and provider values.
- End-to-end nondeterminism is possible at LLM extraction and external embedding
  boundaries, although fixed `CVSchema` ranking arithmetic itself was stable.

### Rejected or Corrected

- The prior report's active-weight normalization allowed a preferred-only JD to
  produce `100.0`. That violated required-skill priority and was corrected to a
  fixed `.8/.2` denominator; preferred-only evidence is now capped at `20.0`.
- BUG_CV_003 and BUG_CV_004 were not proven to be current early-zero bugs. Current
  `rank()` gives proportional partial scores and positive preferred contributions.

## 3. Actual Runtime Architecture

```text
POST /api/v1/cv/evaluate
 -> multipart/JD JSON validation
 -> filename and magic-byte validation
 -> PDF/DOCX text extraction
 -> clean_cv_text and PII redaction
 -> randomized security delimiter and prompt construction
 -> HF model chain, temperature=0.0
 -> balanced JSON extraction
 -> output normalization
 -> CVSchema validation
 -> JobDescription validation
 -> canonical skill matching
 -> required/preferred ratios
 -> deterministic hard-skill score
 -> optional semantic context
 -> JSON response
```

The controlling files are `ai-service/app/main.py`,
`ai-service/app/pipeline/run.py`, `ai-service/app/pipeline/ranking.py`,
`ai-service/app/skills/canonicalize.py`, `ai-service/app/skills/taxonomy.yaml`,
`ai-service/app/providers/hf_provider.py`, and
`ai-service/app/providers/embeddings.py`.

Extraction failures remain HTTP `502`; ranking failures remain HTTP `500`.
File validation failures are HTTP `400`, malformed/invalid JD payloads are `400` or
`422`, and empty extracted text is `422`.

## 4. Reproduction Results

All deterministic probes used `semantic_fit=0`.

| Bug/case | Result before fix | Result after fix | Status |
|---|---:|---:|---|
| BUG_CV_001 exact required match | `70.0` with semantic fit `0` | `80.0` without preferred evidence | FIXED for verified scoring cause |
| BUG_CV_002 fixed validated inputs | stable arithmetic, provider-dependent end-to-end | stable hard-score path; no embedding call | FIXED for scoring nondeterminism |
| BUG_CV_003 2/3 required | positive proportional score | `66.67` | NOT REPRODUCED as zero; regression covered |
| BUG_CV_004 required absent, preferred matched | `14.0` with required list present | `20.0` | NOT REPRODUCED as zero; regression covered |
| Preferred-only with empty required list | `100.0` due active-weight normalization | `20.0` | Required priority fixed |
| No matching skills | `0.0` | `0.0` | Valid zero |
| TC-001 PDF | unavailable | unavailable | NOT REPRODUCED |

The previous formula was verified as:

```text
hard_skill_score = (.8 * required_ratio + .2 * preferred_ratio) / 1.0
final_score = (.7 * hard_skill_score) + (.3 * semantic_fit)
```

The implemented formula is:

```text
hard_skill_score = (.8 * required_ratio + .2 * preferred_ratio) / 1.0
final_score = hard_skill_score
score = round(final_score * 100, 2)
```

Semantic fit remains in the result breakdown for diagnostics but has weight `0.0`.

## 5. Root Cause Analysis

### BUG_CV_001

**Root cause:** `app/pipeline/ranking.py::rank()` previously allowed aggregate
embedding similarity to contribute 30% of the score. A perfect exact match could
therefore score only `70.0` when the embedding returned zero. In addition,
`taxonomy.yaml` lacked the AI Instructor vocabulary, so controlled canonical
matching and aliases were unavailable.

**Evidence:** direct ranking probe, formula constants in `ranking.py`, and taxonomy
contents. Exact TC-001 extraction/missing list: **UNCONFIRMED**, fixture absent.

**Confidence:** high for the architecture defect; unavailable for the original
candidate-specific score.

### BUG_CV_002

**Root cause:** fixed-input arithmetic was deterministic, but end-to-end extraction
can vary because hosted model output is not guaranteed identical even at
temperature `0.0`; prompts include a random `secrets.token_hex(6)` delimiter and
the fallback chain can select another model after failure. Aggregate embeddings
also depend on local/API provider configuration.

**Fix:** the authoritative score no longer depends on embeddings, so repeated
validated inputs cannot change the score through provider output. Security
delimiters were preserved because they protect the untrusted CV boundary.

**Confidence:** high for the removed score dependency; original two numbers remain
unconfirmed without logs.

### BUG_CV_003

**Root cause:** no current root-cause bug was found. `_match_ratio()` returns a
proportion and `rank()` has no early-zero branch. Extraction failure returns `502`,
not score zero. A valid empty `CVSchema` can still be ranked, which was the actual
state-model gap.

**Confidence:** high that the reported behavior is not reproduced by current code;
candidate-specific historical cause unavailable.

### BUG_CV_004

**Root cause:** no current zeroing bug was found. `nice_to_have_skills` has positive
weight and is matched separately. The confirmed defect was observability: the main
response fields contained required matches only.

**Confidence:** high for current behavior; original report remains unconfirmed.

## 6. Implemented Solution

- `ranking.py`: hard matching is now authoritative (`HARD_SKILL_WEIGHT=1.0`,
  `SEMANTIC_WEIGHT=0.0`); embedding calls are skipped when semantic weight is zero;
  semantic values are clamped to `[0,1]` when used.
- `schemas/cv.py`: added optional additive fields for required and preferred matched
  and missing skills; existing fields remain unchanged.
- `canonicalize.py`: added casefolded alphanumeric lookup normalization so casing,
  spaces, and punctuation differences are handled without blanket fuzzy merging.
- `taxonomy.yaml`: added reviewed AI assistant, generative AI, design, and AI
  marketing IDs/aliases, including Gemini, AI Studio, Firefly, Runway, and others.
  Teaching, communication, and portfolio requirements remain non-skill evidence
  and were not incorrectly added as technical skills.
- `pipeline/run.py`: added `extraction_status()` returning `SUCCESS` or `EMPTY`.
- `main.py`: successful responses now include extraction status; model-chain failure
  includes `FAILED` and remains HTTP `502`.

## 7. Why This Solution Was Selected

It removes the external provider from the authoritative number without adding LLM
calls, preserves security redaction and prompt boundaries, and keeps the endpoint
and existing fields backward-compatible. An LLM scoring pass would be less
auditable and more expensive. Blanket fuzzy matching would increase false
positives. Retaining semantic similarity as a hidden weighted score would preserve
the reproducibility defect.

## 8. Scoring Formula

Required and preferred components retain the existing `.8/.2` policy, with a fixed
denominator so missing required evidence cannot be removed from the score. The
final production score is now:

$$
S = 100 \times (0.8R + 0.2P)
$$

where $R$ and $P$ are required/preferred match ratios; an absent component has
ratio zero. Semantic fit is diagnostic only and has no authoritative weight.

## 9. Skill Taxonomy Changes

Added explicit canonical entries and aliases for AI assistants, prompt engineering,
image/video generation, voice/music, AI design, and AI marketing. Examples include:

```text
ChatGPT <-> Chat GPT
Gemini <-> Google Gemini
Google AI Studio <-> AI Studio
Adobe Firefly <-> Firefly
Runway <-> Runway ML
ElevenLabs <-> Eleven Labs
```

`AI`, generic “portfolio”, teaching, communication, and “simplifying complex
concepts” are not collapsed into technical skill IDs. Fuzzy matching remains
conservative and is not used to equate arbitrary AI-related strings.

## 10. Determinism Changes

For fixed validated CV/JD data, taxonomy, scoring configuration, and code version,
the score no longer calls an external embedding provider. Sets are used only for
membership, while output lists follow JD input order. The extraction model can
still produce different valid CVSchemas across independent requests; deterministic
scoring starts after validated extraction. Model, prompt, and taxonomy version
metadata should be persisted by the integration layer for full auditability.

## 11. Extraction State Handling

Successful validated extraction is classified as `SUCCESS` when meaningful CV
evidence exists and `EMPTY` otherwise. Provider, parsing, and validation failure
remains `FAILED` and returns HTTP `502`; it is never converted into score `0`.

## 12. Semantic Similarity

The implementation still supports aggregate CV/JD cosine similarity through local
or API embeddings, including API response ordering by `index`. It is now optional
diagnostic context rather than authoritative skill evidence. With the current
scoring configuration it is not invoked, reducing latency, cost, and provider
failure surface.

## 13. Security Impact

PII redaction, magic-byte file validation, balanced JSON parsing, Pydantic
validation, and prompt injection instructions were preserved. The random prompt
delimiter was deliberately not removed because it is a security boundary. The
deterministic change affects only score calculation and does not expose additional
PII or execute CV content.

## 14. Cost & Performance

Normal extraction remains one LLM call, with up to three attempts only when the
existing fallback chain encounters failures. The ranking path now performs no
embedding HTTP call or local model inference under the authoritative configuration.
This lowers ranking latency, network cost, CPU/memory use, and provider outage
exposure. No repeated LLM calls were introduced.

## 15. Backward Compatibility

The endpoint, request fields, CV fields, existing ranking fields, and error status
codes remain. New result fields and `extraction_status` are additive. Score
semantics change intentionally: semantic fit no longer contributes to `score`.
Consumers relying on the old 70/30 behavior must treat this as a scoring-version
change; the breakdown includes `scoring_version`.

## 16. Tests Added/Modified

- `tests/unit/test_ranking.py`: deterministic semantic isolation, preferred-only
  scoring/evidence, and duplicate skill coverage.
- `tests/unit/test_canonicalize.py`: AI aliases and conservative non-alias behavior.
- `tests/unit/test_extraction_status.py`: `EMPTY` versus `SUCCESS`.
- `tests/unit/test_embeddings.py`: reversed API batch response is reordered by index.
- Existing endpoint and redaction tests continue to pass.

## 17. Final Regression Results

```text
python -m pytest -q ai-service/tests
28 passed
coverage: 59%
```

Focused ranking, canonicalization, and endpoint tests also passed after the fix.
The repository has no accessible TC-001 fixture, so its required real-file test
could not run.

## 18. TC-001 Before vs After

| Field | Before | After |
|---|---|---|
| Fixture file | not found | not found |
| Actual extracted skills | unavailable | unavailable |
| Actual JD | unavailable | unavailable |
| Actual score/breakdown | unavailable | unavailable |
| Deterministic equivalent exact-match probe | `70.0` at semantic `0` | `80.0` without preferred evidence |

No candidate-specific score is claimed. The fixture must be added to the workspace
with its exact JD before this section can be populated.

## 19. Remaining Limitations

- TC-001 extraction and real-provider ranking remain unvalidated because the PDF
  and JD are absent.
- Hosted LLM extraction can still vary; deterministic scoring cannot make an
  unstable extracted CV identical without caching or a persisted extraction result.
- `min_experience_years` remains accepted but unused by ranking.
- Extraction status is currently response-level, not a fully typed internal result
  object; `FAILED` is represented by the HTTP error envelope.
- Taxonomy coverage is improved but must be reviewed against production JDs.
- Full model/prompt/provider version audit metadata is not yet in the response.
- The suite has no real extraction-quality accuracy dataset.

## 20. Final Recommendation

**NOT READY FOR INTEGRATION** for the requested acceptance gate, solely because the
required TC-001 PDF and corresponding JD are unavailable and therefore the real
fixture regression cannot be proved. The deterministic ranking implementation,
security path, backward-compatible response extension, and automated repository
tests are ready for review. Add the fixture and JD, run the real extraction twice,
record the extracted schema and breakdown, then promote the integration status.

Changed Files:
- `ai-service/app/pipeline/ranking.py` - deterministic hard-skill authority and no-op semantic provider when disabled.
- `ai-service/app/pipeline/run.py` - successful extraction state classification.
- `ai-service/app/main.py` - additive extraction status in API responses and failure envelope.
- `ai-service/app/schemas/cv.py` - additive required/preferred evidence fields.
- `ai-service/app/skills/canonicalize.py` - conservative presentation normalization.
- `ai-service/app/skills/taxonomy.yaml` - reviewed AI-domain canonical skills and aliases.
- `ai-service/tests/unit/test_ranking.py` - revised deterministic scoring expectations and regressions.
- `ai-service/tests/unit/test_canonicalize.py` - AI alias regressions.
- `ai-service/tests/unit/test_extraction_status.py` - extraction state regressions.
- `ai-service/tests/unit/test_embeddings.py` - embedding response-order regression.

New Files:
- `CV_RANKING_BUG_FIX_REPORT.md` - second-pass validation, implementation evidence, and acceptance status.

Deleted Files:
- None.