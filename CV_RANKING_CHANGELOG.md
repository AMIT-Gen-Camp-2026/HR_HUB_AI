# CV Ranking Change Changelog and Audit

## Date

2026-09-02

## Scope and evidence

This audit describes the repository state currently visible in the workspace. Evidence used:
Git status/diff statistics and recent history; current `ai-service/app` source; current
`ai-service/tests`; `ai-service/README.md`; `ai-service/docs`; `CV_RANKING_BUG_ANALYSIS.md`;
and `CV_RANKING_BUG_FIX_REPORT.md`.

Git is available. The latest visible commits are `fab5b43 edit endpoints`, `5dbae86 edit`,
`0f32c5a edit for integration`, and `f97a1bd Add CV review project`. The worktree is dirty;
this audit did not revert or modify existing changes. The real TC-001 PDF and JD are now
available under `ai-service/tests/fixtures/tc001/` and were executed in this task.

## Change inventory

| File/component | Before, if verifiable | Current state | Behavior/issue addressed |
|---|---|---|---|
| [ai-service/app/pipeline/ranking.py](ai-service/app/pipeline/ranking.py) | Compared implementation used `HARD_SKILL_WEIGHT=0.7`, `SEMANTIC_WEIGHT=0.3`, raw JD lists, and no top-level preferred evidence. | Hard score is authoritative (`1.0/0.0`); JD lists are deduplicated before matching/ratios; evidence is returned; v2 normalizes complete required matches to 100 and exposes taxonomy version `2026.09`. | Removes provider influence and duplicate JD denominator inflation, and makes scoring reproducible and explainable. |
| [ai-service/app/pipeline/run.py](ai-service/app/pipeline/run.py) | No `extraction_status()` helper was present in the compared diff. | Adds `SUCCESS`/`EMPTY`, explicit taxonomy recovery, and a version-keyed in-memory validated snapshot. | Separates empty output from failure, protects literal skill recall, and avoids repeated model calls for identical configured input. |
| [ai-service/app/main.py](ai-service/app/main.py) | Successful responses had no extraction status; model failure had no status. | Adds response-level `SUCCESS`/`EMPTY`; model-chain failure includes `FAILED`. | Improves operational state visibility without changing the endpoint path or status codes. |
| [ai-service/app/schemas/cv.py](ai-service/app/schemas/cv.py) | `RankingResult` had only `matched_skills` and `missing_skills` for skill evidence. | Adds additive required/preferred matched and missing arrays. | Makes preferred evidence visible while retaining existing fields. |
| [ai-service/app/skills/canonicalize.py](ai-service/app/skills/canonicalize.py) | Lookup used lowercased names and aliases. | Adds casefolded alphanumeric presentation normalization; retains RapidFuzz fallback at threshold 92. | Handles casing, spaces, and punctuation consistently while keeping aliases explicit. |
| [ai-service/app/skills/taxonomy.yaml](ai-service/app/skills/taxonomy.yaml) | Compared diff had no AI-domain block. | Adds the AI, generative-AI, design, and marketing entries listed below. | Adds controlled vocabulary for AI-oriented JDs/CVs. |
| [ai-service/app/providers/hf_provider.py](ai-service/app/providers/hf_provider.py) | No ranking-specific change was shown in the diff. | `temperature=0.0`; validation failures continue through model chain and retry; optional metadata reports the successful model/provider/attempt. | Preserves extraction validation/fallback and makes fallback observable. |
| [ai-service/app/providers/embeddings.py](ai-service/app/providers/embeddings.py) | Semantic fit was available to ranking; API responses are ordered by index. | Local/API embedding support, cache, cosine calculation, and index ordering remain; current ranking configuration skips the call. | Removes embedding provider dependency from the authoritative score while retaining capability. |
| [ai-service/tests/unit/test_ranking.py](ai-service/tests/unit/test_ranking.py) | Existing ranking tests covered earlier behavior. | Adds tests for semantic isolation, preferred evidence, duplicate candidate/JD skills, policy cases, bounds, and provider independence. | Regression protection for the v2 score. |
| [ai-service/tests/unit/test_canonicalize.py](ai-service/tests/unit/test_canonicalize.py) | Existing aliases/unknown-skill tests. | Adds AI aliases and asserts generic `AI` is unknown. | Protects explicit taxonomy aliases and conservative matching. |
| [ai-service/tests/unit/test_extraction_status.py](ai-service/tests/unit/test_extraction_status.py) | No dedicated status test in the compared inventory. | Tests empty versus evidence-bearing schemas. | Protects extraction-state classification. |
| [ai-service/tests/unit/test_embeddings.py](ai-service/tests/unit/test_embeddings.py) | No corresponding test in the compared inventory. | Tests reversed API batch responses are reordered by `index`. | Prevents silent CV/JD vector swaps. |
| [CV_RANKING_BUG_ANALYSIS.md](CV_RANKING_BUG_ANALYSIS.md) | New untracked analysis document. | Records the earlier investigation and recommendations. | Audit trail; historical formula statements are not current source authority. |
| [CV_RANKING_BUG_FIX_REPORT.md](CV_RANKING_BUG_FIX_REPORT.md) | New untracked report. | Records the earlier fix pass. | Audit trail; its single-formula/80-point claims are partly stale against current source/tests. |
| `ai-service/README.md`, `ai-service/docs/*` | Inspected; no ranking-fix diff was reported. | Some examples still describe the former 70/30 behavior. | Documentation drift remains. |

Git also reports `.coverage` artifacts (one modified under `ai-service`, one untracked at
root). They are generated test outputs, not functional source changes. No files were deleted.

## Current ranking algorithm

The current flow is:

```text
candidate.skills + inferred_skills + project technologies + non-empty job titles
  -> candidate canonical membership set and raw lowercase membership set
  -> _unique_skills(required JD) and _unique_skills(preferred JD)
  -> required matching
  -> preferred matching
  -> ratios over deduplicated JD lists
  -> required-coverage score plus bounded preferred bonus
  -> semantic fit forced to 0 without provider call
  -> rounded score
```

`canonicalise()` is applied to candidate and JD names. Candidate values are not emitted as a
deduplicated list, but canonical and raw sets prevent duplicate candidate values from
increasing match counts. Matching output follows the deduplicated JD order. A skill matches
when its canonical ID is present in the candidate canonical set, or when the lowercased
requested text equals/is contained in a candidate raw skill string.

`_unique_skills()` preserves the first display value and uses:

```text
canonicalise(skill) or skill.strip().casefold()
```

Thus known aliases resolve to canonical IDs before deduplication; unknown skills use raw
casefolded text. The current constants are:

```text
REQUIRED_WEIGHT = 0.8
NICE_TO_HAVE_WEIGHT = 0.2
HARD_SKILL_WEIGHT = 1.0
SEMANTIC_WEIGHT = 0.0
```

The exact current score is:

```text
R = matched_required / unique_required, or None if no required skills
P = matched_preferred / unique_preferred, or None if no preferred skills

if R is not None:
  H = R + (0.2 * P * (1 - R))
else:
  H = 0.2 * P

score = round(min(H, 1.0) * 100, 2)
```

For a missing preferred list, `P` is treated as zero. With required skills this is
equivalent to `100R + 20P(1-R)`, capped at 100. With no required skills, preferred
evidence is capped at 20 points.

## JD deduplication fix

### Before

The compared implementation matched the original JD lists and calculated ratios against
their original lengths. Equivalent duplicate required entries increased
`required_skills_total` and the required denominator; equivalent preferred entries likewise
increased `nice_to_have_skills_total` and its denominator. Duplicate values could therefore
reduce ratios and score incorrectly.

### After

`required_skills` and `preferred_skills` are created with `_unique_skills()` before matching.
Those lists drive matching, ratios, output evidence, and breakdown totals. Required and
preferred JD skills are deduplicated. Candidate skills are not converted into an ordered
unique list, but canonical/raw sets prevent their duplicates inflating counts. Canonical IDs
and aliases are resolved before deduplication when known. First-seen JD order and spelling
are retained.

Actual example:

```text
JD before:    Python, python, SQL
candidate:    Python
old total:    3
old matched:  2 (both Python spellings)
old ratio:    2/3 = 0.6667

JD now:       Python, SQL
candidate:    Python
new total:    2
new matched:  1
new ratio:    1/2 = 0.5
new score:    50.0 with no preferred skills
```

The first captured failing run returned 26.67 because it exercised the pre-deduplication
ratio path. The latest focused run did not fail this duplicate-JD test; a completed full
post-edit run was not captured.

## Perfect required match policy

A perfect required match now always receives `100.0`, regardless of the number of required
skills or preferred coverage: when `R=1`, the preferred bonus is zero and the required base
is one. This is coherent normalization rather than a cardinality-specific patch.

## Required versus preferred cases

These values are derived from the current source after deduplication:

| Case | Current score |
|---|---:|
| All required and all preferred matched | 100.0. |
| All required matched, no preferred matched | 100.0. |
| Partial required, all preferred matched | `100 * (R + 0.2P(1-R))`. |
| Required exists, none required matched, preferred matched | `100 * 0.2P`; fully matched preferred list is 20.0. |
| No required skills, preferred matched | `100 * 0.2P`; fully matched preferred list is 20.0. |
| No matching skills | 0.0. |
| Duplicate skills | Equivalent JD duplicates are removed; candidate duplicates do not increase counts. |

Preferred coverage contributes only to the uncovered portion of the required score.

## Bug status

### BUG_CV_001: near-perfect candidate around 23.3

**Status: PARTIALLY FIXED / REAL TC-001 VALIDATED, HISTORICAL SCORE UNVERIFIED.**

The real fixture is now available and was processed. The historical candidate-specific 23.3,
expected range, and before/after comparison are not established by repository evidence. The
compared implementation had a confirmed 30% semantic contribution; the current configuration
removes it, adds explicit AI taxonomy vocabulary, and normalizes every complete required match
to 100.0. The live TC-001 result is documented below.

### BUG_CV_002: same CV/JD around 23.3 then 31.6

**Status: PARTIALLY FIXED / EXTRACTION VARIABILITY CONFIRMED.**

For fixed validated `CVSchema`, `JobDescription`, taxonomy, code, and scoring configuration,
authoritative arithmetic is deterministic and no embedding call occurs with semantic weight
zero. Sets are membership-only; output lists follow JD order. Embedding API results are sorted
by index and cache keys are content hashes.

This is not full end-to-end determinism. Hosted extraction can return different valid schemas
even at `temperature=0.0`; the prompt includes `secrets.token_hex(6)`, fallback/retry can use
a different model, and provider/model versions and settings can vary. The original two values
remain unknown/unverified. Three live runs produced different validated schemas and scores
(4.17, 6.25, and 14.58), proving extraction variability in the current provider path.

### BUG_CV_003: required-skill candidate around zero

**Status: NOT REPRODUCED.**

There is no early-zero branch for partial required evidence. With no preferred list, partial
coverage returns `100R`; with preferred values it returns `100*(R+0.2P(1-R))`. A candidate with
no matching evidence can legitimately score zero. An empty valid schema can reach ranking and
score zero. A model-chain failure is HTTP 502 and does not become score zero.

### BUG_CV_004: preferred-skill candidate around zero

**Status: PARTIALLY FIXED / ACTUAL ZERO NOT REPRODUCED.**

Preferred values are matched separately, contribute `20P`, and appear in
`matched_preferred_skills`, `missing_preferred_skills`, and `breakdown`. A fully matched
preferred-only candidate scores 20.0 whether required skills are absent or present but
unmatched. Duplicate preferred values are deduplicated. The historical zero is not reproduced;
the verified former issue was top-level response observability.

## Canonicalization and taxonomy

The current canonicalization order is:

```text
strip
 -> casefold and remove non-alphanumeric characters
 -> exact canonical-name/alias lookup
 -> RapidFuzz WRatio fallback at threshold 92
 -> canonical ID or None
```

The taxonomy additions are:

| ID | Name | Aliases | Category |
|---|---|---|---|
| `skill.chatgpt` | ChatGPT | `chatgpt`, `chat gpt` | ai_assistant |
| `skill.claude` | Claude | none | ai_assistant |
| `skill.gemini` | Gemini | `google gemini` | ai_assistant |
| `skill.microsoft_copilot` | Microsoft Copilot | `copilot` | ai_assistant |
| `skill.perplexity` | Perplexity | none | ai_assistant |
| `skill.google_ai_studio` | Google AI Studio | `ai studio` | ai_assistant |
| `skill.notebooklm` | NotebookLM | `notebook lm` | ai_assistant |
| `skill.prompt_engineering` | Prompt Engineering | none | ai_practice |
| `skill.ai_image_generation` | AI Image Generation | none | generative_ai |
| `skill.midjourney` | Midjourney | none | generative_ai |
| `skill.chatgpt_image_generation` | ChatGPT Image Generation | `chatgpt image gen` | generative_ai |
| `skill.adobe_firefly` | Adobe Firefly | `firefly` | generative_ai |
| `skill.leonardo_ai` | Leonardo AI | `leonardo` | generative_ai |
| `skill.flux` | Flux | none | generative_ai |
| `skill.ideogram` | Ideogram | none | generative_ai |
| `skill.recraft` | Recraft | none | generative_ai |
| `skill.ai_video_generation` | AI Video Generation | none | generative_ai |
| `skill.runway` | Runway | `runway ml` | generative_ai |
| `skill.kling` | Kling | none | generative_ai |
| `skill.pika` | Pika | none | generative_ai |
| `skill.luma` | Luma | none | generative_ai |
| `skill.heygen` | HeyGen | `hey gen` | generative_ai |
| `skill.synthesia` | Synthesia | none | generative_ai |
| `skill.elevenlabs` | ElevenLabs | `eleven labs` | generative_ai |
| `skill.playht` | PlayHT | `play ht` | generative_ai |
| `skill.adobe_podcast` | Adobe Podcast | none | generative_ai |
| `skill.suno` | Suno | none | generative_ai |
| `skill.udio` | Udio | none | generative_ai |
| `skill.canva_ai` | Canva AI | `canva ai` | ai_design |
| `skill.gamma` | Gamma | none | ai_design |
| `skill.tome` | Tome | none | ai_design |
| `skill.adobe_express` | Adobe Express | none | design |
| `skill.figma_ai` | Figma AI | none | ai_design |
| `skill.ai_copywriting` | AI Copywriting | none | ai_marketing |
| `skill.social_media_content_creation` | Social Media Content Creation | none | ai_marketing |
| `skill.email_marketing` | Email Marketing | none | marketing |
| `skill.seo_with_ai` | SEO with AI | `ai seo` | ai_marketing |
| `skill.content_strategy` | Content Strategy | none | marketing |
| `skill.ai_marketing_campaigns` | AI Marketing Campaigns | `ai powered marketing campaigns` | ai_marketing |
| `skill.branding_with_ai` | Branding with AI | `ai branding` | ai_marketing |

Generic `AI` is deliberately not a taxonomy entry and the test asserts `canonicalise("AI")
is None`. The inspected taxonomy provides no evidence that communication, teaching,
portfolio, or simplifying complex concepts are technical skills. Explicit aliases are
preferred over blanket fuzzy equivalence, although the existing thresholded fuzzy fallback
remains and should be monitored.

## Extraction status

`extraction_status()` returns `SUCCESS` if any of skills, inferred skills, experience,
projects, education, certifications, languages, or `personal_info.name` is present;
otherwise it returns `EMPTY`. `FAILED` is assigned by the endpoint when
`ModelInferenceError` escapes the model chain.

Validated success returns HTTP 200 with `SUCCESS` or `EMPTY`, including when ranking is
enabled. All model attempts failing returns HTTP 502 with `FAILED`. Empty raw file text
returns HTTP 422 before model/ranking. An empty but valid `CVSchema` now returns HTTP 200
with `ranking: null`; it does not enter ranking. A valid non-empty CV with no matching
skills still receives numeric score zero.

## Semantic embeddings

Before, the compared formula allowed semantic fit to contribute 30%:

```text
score = 100 * (.7 * hard_skill_score + .3 * semantic_fit)
```

Current configuration is:

```text
fit = 0.0                         # provider is not called
score = 100 * (1.0 * H + 0.0 * fit)
```

Embedding implementation remains available for local/API use, but it does not affect ranking,
tie-breaking, or score under current configuration. Benefits: deterministic authoritative
arithmetic, lower latency/cost, and lower provider failure exposure. Costs: less semantic
context and possible quality loss for related skills absent from taxonomy. This is a policy
trade-off, not a universal quality claim.

## Security impact

PII redaction, magic-byte/file validation, balanced JSON extraction, Pydantic validation,
server-side prompt instructions, and prompt-injection delimiters remain in the inspected
path. No security mechanism was removed by the ranking changes. The random delimiter remains
a deliberate boundary around attacker-controlled CV text; it prevents identical prompt bytes
across requests and therefore does not make extraction end-to-end deterministic.

## API compatibility

The endpoint and request fields remain. Existing `score`, `matched_skills`,
`missing_skills`, `semantic_fit`, and `breakdown` remain. Additive fields are
`matched_required_skills`, `missing_required_skills`, `matched_preferred_skills`,
`missing_preferred_skills`; `extraction_status` is additive at the response envelope and
failure envelope. No fields were removed or renamed.
Successful responses also expose additive `extraction_metadata` when available, including
`model_used`, `provider`, `attempt_number`, `fallback_occurred`, and `cache_hit`.

HTTP behavior remains 400/422 for request/file validation, 422 for empty raw extraction,
502 for model-chain failure, 500 for unexpected server/ranking failure, and 200 for success.
The score meaning changed: semantic fit no longer contributes and duplicate JD entries no
longer alter ratios. This is a **BEHAVIORAL/API SEMANTIC CHANGE** despite compatible JSON
shape. `scoring_version` is included in `ranking.breakdown` as
`deterministic-hard-skills-v2`.

## Experience scoring

`min_experience_years` is accepted by `JobDescription` but is not read by `ranking.rank()`.
It has no current effect on score or match lists. This verified limitation remains a pending
product-policy decision and was not implemented in this documentation pass.

## Tests

Captured full-suite command:

```text
cd "d:\github project\HR_HUB_AI\ai-service"; python -m pytest -q tests
```

The earlier captured run reported 29 passed and 2 failed before the final policy change.
The latest complete post-edit run was:

```text
python -m pytest -q tests --no-cov
44 tests selected; 44 passed, 0 failed
```

The latest focused run was:

```text
python -m pytest -q tests/unit/test_ranking.py tests/unit/test_canonicalize.py tests/unit/test_extraction_status.py tests/unit/test_embeddings.py
```

The complete suite passed with coverage enabled at 67.45% (682 statements, 222 missed),
above the configured 49% threshold. A prior focused subset failed coverage at 39.93%
because it selected too few files; this was a coverage configuration artifact.

All ranking policy assertions now pass, including semantic isolation, duplicate invariance,
perfect required matches, partial matches, preferred-only hierarchy, score bounds, and
embedding-provider independence. The duplicate-JD test that previously returned 26.67
also passes after deduplicated ratios were introduced.

The complete suite is the authoritative current result.

### Regression matrix

| Area | Current evidence | Purpose |
|---|---|---|
| Exact required match | One or multiple required skills = 100 when fully matched | BUG_CV_001 policy |
| Duplicate JD skills | Deduplicated totals/ratios; regression passes | Denominator regression |
| Partial required 2/3 | Captured full run passed | BUG_CV_003 proportional score |
| Preferred-only | Captured full run passed at 20.0 | BUG_CV_004 contribution |
| Empty required + preferred | Captured full run passed at 20.0 | Required-priority cap |
| Semantic isolation | Score independent and provider-independent; regression passes | BUG_CV_002 |
| AI aliases | Canonicalization tests in captured suite | Taxonomy |
| Empty extraction | Dedicated tests in captured suite | `EMPTY`/`SUCCESS` |
| Failed extraction | Dedicated endpoint regression returns HTTP 502 and `FAILED` without ranking | `FAILED` |
| Embedding order | Dedicated index-order test | Provider correctness |

## Real TC-001 Results

Fixture paths:

```text
ai-service/tests/fixtures/tc001/candidate.pdf
ai-service/tests/fixtures/tc001/jd.json
```

The PDF extracted to 804 characters. The JD normalizer accepted `job_title`, flattened its
six grouped required-skill arrays into 48 required skills, and mapped the two
`preferred_qualifications` strings to preferred evidence. `min_experience_years` is not
present in this fixture.

Baseline before JD-shape normalization failed with Pydantic validation: missing `title` and
`required_skills` was a dict rather than a list. After normalization, the first live run
returned `SUCCESS`, 2/48 required matches, 0/2 preferred matches, and score `4.17`.

The model extraction itself did not reliably preserve the literal skill section: the first
successful run returned an empty `skills` list and generic inferred skills. After explicit
taxonomy-term recovery was added, a later successful run returned 36 canonical skills,
31/48 required matches, 0/2 preferred matches, and score `64.58`. Its ranking metadata was:

```text
required_match_ratio = 0.6458333333333334
nice_to_have_match_ratio = 0.0
hard_skill_score = 0.6458
semantic_fit = 0.0
taxonomy_version = 2026.09
scoring_version = deterministic-hard-skills-v2
status = SUCCESS
```

The historical `23.3` and expected score are not specified by the fixture and cannot be
claimed as reproduced or disproved by these runs.

## Repeated TC-001 Results

Before explicit recovery, two additional successful runs produced scores `6.25` and `14.58`
with different extracted inferred-skill sets. This confirms extraction variability, not
ranking arithmetic variability. A later live attempt was interrupted by a provider/network
timeout before producing a validated schema. The post-hardening successful run above proves
the fixture can be processed, but three completed post-hardening runs were not obtained.

For every validated schema, ranking uses the same deterministic v2 formula; embedding fit is
zero and cannot alter the authoritative score. No historical before/after score comparison is
available.

## Optimality and ranking quality review

- **Monotonicity:** valid preferred matches add points in scored branches; duplicate handling
  prevents count inflation. Branch-dependent normalization is not uniformly intuitive.
- **Deduplication:** the current complete run confirms the suite executes after the source
  change; the duplicate-JD test did not fail. Candidate/JD duplicate invariance is covered
  by source logic and the available tests.
- **Required dominance:** required coverage is the base score; preferred-only evidence is
  capped at 20 and preferred bonus applies only to uncovered required coverage. Semantic fit
  cannot override it now.
- **Normalization:** the capped formula keeps scores in 0-100 and complete required
  coverage at 100.
- **Stability:** fixed validated inputs have deterministic arithmetic without embeddings;
  upstream extraction remains variable.
- **Auditability:** evidence lists, ratios, breakdown, formula, and version explain results;
  stale examples in older docs remain a documentation risk.

## What Is NOT Fixed

- The historical candidate-specific acceptance scores remain unavailable for comparison,
  although the real TC-001 fixture is now processed.
- End-to-end extraction is not guaranteed deterministic because hosted outputs, random prompt
  delimiters, fallback models, providers, and versions can vary.
- `min_experience_years` is unused.
- Taxonomy coverage is finite and thresholded fuzzy matching remains a review point.
- The labelled extraction-quality dataset is empty according to repository documentation.
- Prompt version is internal cache metadata rather than a public response field.
- `EMPTY` is now returned as an unranked response (`ranking: null`); the numeric score field
  is absent from that response because no ranking was performed.
- README/docs examples still contain prior 70/30 behavior.

## Regression risks

Score distributions and consumers relying on old 70/30 semantics may change. Preferred-only
and no-required JDs now top out at 20. Expanded aliases can create new matches. Removing
semantic scoring can lower quality for related untaxed skills. Extraction variability remains
upstream. The new bounded preferred bonus should be monitored against product expectations.
Unknown-skill substring fallback can also match a requested phrase within a longer candidate
string, which is existing behavior.

## Final bug matrix

| Bug | Root cause | Current status | What changed | Evidence | Remaining gap |
|---|---|---|---|---|---|
| BUG_CV_001 | Prior semantic contribution and missing AI vocabulary were verified architectural causes; historical score has no baseline artifact. | **PARTIALLY FIXED / TC-001 VALIDATED** | Semantic weight disabled; taxonomy/evidence recovery added; perfect required matches normalize to 100. | Real fixture run: 31/48 required, 64.58; full tests. | Extraction quality remains below ideal and no historical comparison exists. |
| BUG_CV_002 | Hosted extraction/provider variability was confirmed; embeddings previously affected score. | **PARTIALLY FIXED** | Hard score no longer depends on embeddings; versioned in-memory snapshot and fallback metadata added. | Live scores 4.17, 6.25, 14.58; cache/provider tests. | Cache is process-local; first extraction can still vary or fail. |
| BUG_CV_003 | Historical early-zero cause not found. | **NOT REPRODUCED** | Status classification and partial-score coverage added. | No early-zero branch; partial test passed. | Legitimate no-match remains numeric zero by design. |
| BUG_CV_004 | Historical zero not found; preferred evidence was previously hidden from top-level fields. | **PARTIALLY FIXED / ACTUAL ZERO NOT REPRODUCED** | Preferred evidence is scored and exposed additively. | Preferred tests and schema diff. | Product may choose different preferred weighting. |

## Hardening Problems and Results

## Round 3 - Closing Confirmed Gaps (2026-09-03)

### G1 - Original fixture validation

**Status: UNVERIFIED.** Workspace search did not find `CV_001`, `CV_004`, `CV_005`,
`TC-001_Happy_Path_Near_Perfect_Match.pdf`, or `AI_instructor.txt`. The available
`tests/fixtures/tc001/` PDF/JD is a substitute fixture and is labeled separately in this
audit. No original CV was fabricated or added.

### G2 - Taxonomy recovery as a permanent stage

**Status: FIXED.** Every uncached extraction scans the same redacted text sent to the model
using bounded exact names/aliases from `taxonomy.yaml`, then unions canonical results with
the validated LLM skills. `taxonomy_recovered_skills` identifies terms found only by the
scan. Word-boundary and explicit-term tests protect against partial-word matches. Cached
schemas retain this attribution and are revalidated on reuse.

### G3 - Bidirectional raw matching

**Status: FIXED.** Raw fallback now supports both containment directions, while either
containment direction requires a four-character term; exact matches and canonical/alias
matches remain unrestricted. Tests cover a non-taxonomy shortened candidate term and reject
the one-character `R` versus `HR Analytics` false positive.

### G4 - Semantic-fit decision

**Status: INVESTIGATED / KEPT DISABLED BY EXPLICIT DECISION.** Ranking tests prove the
authoritative result is independent of semantic-provider output. Live extraction variability
was observed upstream; no evidence justified adding a new provider-dependent score signal.
`SEMANTIC_WEIGHT=0.0` remains intentional and is recorded in `docs/DECISIONS.md`; semantic
fit remains available for future product evaluation.

### G5 - Snapshot retention bound

**Status: FIXED.** The process-local snapshot is now a one-hour TTL, 128-entry LRU cache.
Entries contain validated schema data, including possible PII, and are revalidated on read.
Version/content/model-key invalidation remains intact. TTL, eviction, reuse, and model-change
invalidation tests pass. No external cache or disk persistence was introduced.

### G6 - JD pseudo-skill pollution

**Status: INVESTIGATED / INPUT-QUALITY LIMITATION CONFIRMED.** The Streamlit UI maps every
non-empty line directly into the flat skill arrays, so pasted section headings and narrative
sentences become literal requirements. The ranking algorithm was not loosened. The finding
and recommended additive warning are documented in `docs/FULLSTACK_INTEGRATION.md`; no
silent schema or matching change was made.

### Round 3 validation evidence

The available substitute TC-001 fixture was processed successfully. A baseline before JD
normalization failed Pydantic validation because its title/key shape and grouped skill object
did not match the flat API schema. After normalization, the first successful run scored 4.17
(2/48 required, 0/2 preferred). A later run with deterministic taxonomy recovery scored 64.58
(31/48 required, 0/2 preferred). Earlier uncached runs scored 6.25 and 14.58, demonstrating
provider extraction variability. A later provider attempt timed out. These are not original
historical CV_001/CV_004/CV_005 results.

## Round 3 regression results

Focused hardening/security slice:

```text
python -m pytest -q tests/unit/test_hf_provider.py tests/unit/test_extraction_snapshot.py tests/unit/test_redaction_integration.py tests/unit/test_canonicalize.py tests/unit/test_extraction_status.py tests/unit/test_ranking.py tests/integration/test_auth.py tests/integration/test_rank_endpoint.py --no-cov
40 passed, 0 failed
```

Complete suite:

```text
python -m pytest -q tests
44 passed, 0 failed
coverage: 67.45%
```

The suite emitted only the existing Flask-Limiter in-memory-storage warning. Static
diagnostics reported no errors in touched source/test files, and `git diff --check` was clean.

### Problem 1 - TC-001 validation

The real PDF and grouped JD are now accepted. The JD adapter is additive and preserves the
flat `JobDescription` API shape. The live result is `SUCCESS`; extraction quality and
provider variability remain limitations rather than being hidden.

### Problem 2 - End-to-end determinism

Ranking determinism is confirmed for validated schemas. Three pre-hardening live runs varied
because extraction varied; one later live provider attempt timed out. The random security
delimiter was preserved. A process-local versioned snapshot now avoids repeated model calls
without adding a persistence service or writing CV/PII data to disk. Its key includes the
cleaned-content hash, prompt version, schema version, taxonomy version, and model chain.

### Problem 3 - FAILED extraction

The endpoint now has a dedicated regression test proving `ModelInferenceError` returns HTTP
502 and `extraction_status=FAILED` without a ranking object or score zero.

### Problem 4 - EMPTY extraction

`EMPTY` now returns HTTP 200 with `ranking: null` and does not invoke ranking. This preserves
the existing response shape while preventing an extraction failure from masquerading as a
numeric zero. Legitimate non-empty no-match candidates still receive score 0.

### Problem 5 - Fuzzy matching

Explicit aliases remain preferred, generic `AI` remains unknown, and the existing threshold
92 fuzzy fallback remains. Explicit taxonomy recovery uses bounded exact term matching only;
it does not broaden fuzzy equivalence.

### Fallback transparency

`query_model()` records the actual successful `model_used`, `provider`, `attempt_number`,
and `fallback_occurred`. The endpoint exposes these values additively in
`extraction_metadata`; cache hits identify `versioned-in-memory-snapshot` and attempt 0.
No credentials or prompt contents are exposed. A regression test simulates primary failure
and verifies that fallback model and attempt 2 are reported.

### Performance review

Cache misses use the existing extraction chain. A cache hit revalidates the stored
`CVSchema` and skips model invocation. Cache invalidation occurs when cleaned content, model
chain, prompt version, schema version, or taxonomy version changes. The snapshot is
process-local and does not survive restarts; no cross-process latency improvement is claimed.
Ranking remains a single canonicalization/matching pass with set membership and no embedding
call.

### Historical fixture search

The real TC-001 fixture is present and validated above. The historical `CV_001`, `CV_004`,
`CV_005`, and `TC-001_Happy_Path_Near_Perfect_Match.pdf` artifacts were not found in the
available workspace evidence. Their original incidents remain unverified; TC-001 evidence
is current-fixture evidence only.

### Problem 6 - Ranking invariants

The v2 formula and regression tests cover perfect required matches, proportional required
coverage, preferred monotonicity, duplicate JD/candidate invariance, bounds, no-match zero,
and provider independence. The complete suite passes.

### Problem 7 - Taxonomy versioning

`taxonomy_version=2026.09` is included in `ranking.breakdown` alongside
`scoring_version=deterministic-hard-skills-v2`. Successful extraction metadata is exposed
additively at `extraction_metadata` with `model_used`, `provider`, `attempt_number`,
`fallback_occurred`, and `cache_hit` where available.

### Problem 8 - Documentation drift

This changelog records historical 70/30 behavior only as historical behavior. Older reports
and some integration examples still contain those historical values and should not be read
as the current policy.

### Problem 9 - Experience requirement

`min_experience_years` remains accepted but unused by ranking. The TC-001 PDF mentions five
years, but the fixture JD does not provide a structured minimum-years field; no new scoring
dimension was introduced.

## Final Engineering Assessment

# READY FOR REVIEW — EXTRACTION QUALITY INVESTIGATION INCOMPLETE

The architectural changes are reviewable: semantic fit is no longer authoritative, JD
deduplication exists in current source, AI aliases and extraction states are represented,
and API additions are backward-compatible in shape. The complete suite passes and the real
TC-001 fixture has been processed, but extraction remains provider-dependent and only one
completed post-hardening live run was captured; a controlled primary-versus-fallback quality
comparison is not available. Review should confirm whether the live 64.58 result is acceptable
for the product's extraction-quality target before integration.
Security protections remain intact; ranking and regression tests were changed, plus the
minimal JD compatibility and explicit taxonomy-recovery hardening.
