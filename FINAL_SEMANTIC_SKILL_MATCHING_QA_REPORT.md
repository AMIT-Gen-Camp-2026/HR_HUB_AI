# CV/JD Semantic Skill-Matching Redesign
## Final QA Handoff Report

**Date:** 2026-09-13  
**Scope:** CV ranking skill matching, semantic judge providers, caching, security boundaries, and validation evidence

## Executive Result

The original deterministic substring-matching defect has been removed and replaced with taxonomy-gated, batched LLM capability judgment.

The redesigned path was validated through two independent live provider runs after the initial failed Qwen experiment. Both successful runs produced graded, evidence-based results and refused to infer unsupported SQL operations, including `SELECT`, `JOIN`, and `WHERE` clauses. The provider fallback chain also worked during real Gemini outages.

Gemini's original 404 was traced to provider-side model availability: the configured `gemini-2.5-flash` model was listed but unavailable to new users. The primary model is now `gemini-3.8-flash`, with the current free-tier fallbacks `gemini-3.7-flash` and `gemini-3.5-flash-lite`. During the latest live run, Gemini returned `503 Service Unavailable`, so the chain correctly failed over to Groq. Gemini has not yet been observed successfully answering as the primary provider; this remains an availability verification item.

---

## 1. Original Bug and Root Cause

### Faulty matching behavior

The original `_match_against_candidate()` implementation in `app/pipeline/ranking.py` iterated over the JD requirement list:

```python
for skill in skills:
    canon = canonicalise(skill)
    skill_clean = skill.strip().lower()

    if canon is not None and canon in candidate_canonical:
        matched.append(skill)
    elif any(
        skill_clean == raw
        or (len(skill_clean) >= 4 and skill_clean in raw)
        or (len(raw) >= 4 and raw in skill_clean)
        for raw in candidate_raw_lower
    ):
        matched.append(skill)
```

The parameter named `skills` was populated with `required_skills` from the job description. Therefore, when the condition passed, `matched.append(skill)` appended the JD requirement text itself.

The returned value then flowed into:

```python
RankingResult(
    matched_skills=matched_required,
    ...
)
```

The result therefore represented the JD text as if it were candidate-derived evidence.

### Why the match was incorrect

The raw fallback treated textual containment as capability equivalence:

```python
skill_clean in raw
or raw in skill_clean
```

This logic did not distinguish:

- A generic technology mention from a specific operational capability.
- “SQL & Data Validation” from writing `SELECT`, `JOIN`, and `WHERE` queries.
- A short domain label from a compound requirement containing several material clauses.
- A technology name from evidence of production depth, syntax, or database breadth.

### Concrete production symptom

Candidate evidence:

```text
SQL & Data Validation
Executed SQL queries for backend data integrity checks ensuring proper data mapping and transaction logging
```

JD requirement:

```text
Execute SQL queries (SELECT, JOINs, WHERE clauses) to perform backend database testing.
```

The candidate did not explicitly mention `SELECT`, `JOIN`, or `WHERE`, but the old matcher could treat the requirement as matched and produce a complete required-skill match. Because the JD string itself was appended to `matched_skills`, the response appeared to contain verified candidate evidence even though it came from the JD.

---

## 2. Solution Implemented

### 2.1 New architecture

The ranking path now has two stages:

```text
Candidate CV + JD requirements
        |
        v
Stage 1: taxonomy coarse filter
        |
        | no candidate-side taxonomy signal
        |------------------------------> 0% evaluation, no judge call for that requirement
        |
        v
Stage 2: batched LLM semantic capability judge
        |
        v
Structured SkillEvaluation results
        |
        v
Average satisfaction scoring
```

### Stage 1: taxonomy coarse filter

The existing `canonicalise()` and taxonomy layer remains the coarse domain filter. It is used to decide whether the candidate contains evidence from a recognized skill domain worth sending to the judge.

The raw substring fallback was removed entirely. No partial or refactored version of the former `skill_clean in raw` / `raw in skill_clean` logic remains in the ranking path.

### Stage 2: semantic capability judge

Requirements that pass the coarse filter are evaluated in one batched call per candidate/JD pair whenever possible.

The judge receives:

- Exact requirement text.
- Relevant candidate-side evidence only.
- Explicit skills.
- Inferred skills.
- Project names and descriptions.
- Project technologies.
- Experience entries.

The full raw CV is not sent to the ranking judge.

### 2.2 Multi-provider fallback chain

The provider order is:

```text
1. Gemini 3.6 Flash
2. GPT-OSS-120B via Groq
3. Llama 3.3 70B free-tier entry via OpenRouter
```

The implementation is in `app/providers/judge_provider.py`.

Each provider normalizes its raw response into the same structured result. On any of the following conditions, the provider is logged as failed and the next provider is attempted:

- Authentication/API error.
- HTTP error.
- Rate limit.
- Timeout or connection failure.
- Malformed response.
- Wrong evaluation count.
- Requirement order mismatch.
- Evidence quote not found in candidate evidence.

The answering provider and model are returned through judge metadata:

```python
JudgeResponse(
    evaluations=evaluations,
    provider=provider_name,
    model=model_name,
)
```

### 2.3 Few-shot judge prompt

`JUDGE_SYSTEM_PROMPT` now includes generic examples from a non-SQL domain.

Positive example:

```text
Requirement: Configure HTTPS with certificate rotation and monitor expiry.
Evidence: Configured HTTPS termination, automated certificate renewal, and
expiry alerts for production services.
Correct judgment: 95.
```

Negative example:

```text
Requirement: Build, deploy, monitor, and roll back containerized services.
Evidence: Used containers during local development.
Correct judgment: 20.
```

The negative example explicitly demonstrates that a general technology mention does not prove every operation in a compound requirement.

### 2.4 Output contract

The authoritative per-requirement output is:

```python
class SkillEvaluation(StrictModel):
    requirement: str
    satisfaction_percent: float = Field(ge=0.0, le=100.0)
    reasoning: str
    evidence_quote: str
```

`RankingResult` now includes:

```python
skill_evaluations: List[SkillEvaluation]
```

The legacy fields remain for backward compatibility:

```python
matched_skills: []
missing_skills: []
matched_required_skills: []
missing_required_skills: []
matched_preferred_skills: []
missing_preferred_skills: []
```

They are intentionally empty in the redesigned path. JD strings are no longer presented as candidate facts.

### 2.5 Scoring

The scoring formula structure remains unchanged:

```python
required_ratio = average(required satisfaction percentages) / 100
nice_ratio = average(preferred satisfaction percentages) / 100
preferred_bonus = NICE_TO_HAVE_WEIGHT * nice_ratio * (1 - required_ratio)
hard_skill_score = required_ratio + preferred_bonus
final_score = HARD_SKILL_WEIGHT * hard_skill_score
score = round(final_score * 100, 2)
```

Only the individual requirement contribution changed from binary values to satisfaction percentages.

`REQUIRED_WEIGHT`, `SEMANTIC_WEIGHT`, and `semantic_fit()` were not changed. `SEMANTIC_WEIGHT` remains `0.0`; the new LLM judge contributes through `skill_evaluations` and the hard-skill averages.

### 2.6 Redis-backed caching

Both cache mechanisms now use a shared cache abstraction:

```python
cache_backend.get(key)
cache_backend.set(key, value, ttl_seconds)
```

Redis keys are namespaced:

```text
snapshot:{hash}
judge:{hash}
```

Extraction snapshot keys preserve the original composition:

```python
{
    "document_hash": sha256(cleaned_text),
    "prompt_version": EXTRACTION_PROMPT_VERSION,
    "schema_version": SCHEMA_VERSION,
    "taxonomy_version": TAXONOMY_VERSION,
    "models": config.MODEL_CHAIN,
}
```

Judge cache keys include:

```python
{
    "candidate_hash": sha256(serialized_candidate),
    "job_description_hash": sha256(serialized_job_description),
    "judge_prompt_version": "ranking-judge-v1",
    "taxonomy_version": TAXONOMY_VERSION,
    "judge_model_chain": config.JUDGE_MODEL_CHAIN,
}
```

Redis behavior:

- Redis is attempted at startup.
- If unavailable, a warning is logged and the in-memory backend is used.
- If Redis fails during a read or write, the operation falls back per call.
- Existing TTL behavior is preserved at 3600 seconds.
- The in-memory fallback preserves bounded LRU behavior.

---

## 3. Validation History

All rounds used the same candidate evidence:

```text
SQL & Data Validation
Executed SQL queries for backend data integrity checks ensuring proper data mapping and transaction logging
```

All rounds evaluated these four requirements:

1. `Execute SQL queries (SELECT, JOINs, WHERE clauses) to perform backend database testing`
2. `Ability to write fundamental SQL queries for relational databases (MySQL, PostgreSQL, or SQL Server)`
3. `Should be comfortable filtering, sorting, and combining data across multiple database tables`
4. `Strong SQL skills required`

### Round 1: Qwen 3B via Hugging Face

**Result: Failed.**

The model assigned 90% to all four requirements and hallucinated unsupported capabilities.

| Requirement | Score | Model behavior | Result |
|---|---:|---|---|
| SQL queries with SELECT/JOIN/WHERE for backend testing | 90% | Claimed SELECT, JOIN, and WHERE support from generic SQL-query evidence | Failed |
| Fundamental SQL queries across MySQL/PostgreSQL/SQL Server | 90% | Claimed database-platform breadth not present in the evidence | Failed |
| Filtering, sorting, and combining data across tables | 90% | Claimed unsupported filtering, sorting, and table-combination experience | Failed |
| Strong SQL skills | 90% | Treated generic SQL evidence as proof of strong expertise | Failed |

The output reproduced the original semantic false-positive problem even though the raw substring matcher had been removed.

### Round 2: Groq GPT-OSS-120B, Gemini returning 404

**Result: Passed.**

Gemini was unavailable with the previous model configuration and returned 404. The chain fell back to Groq.

Actual Groq output:

| Requirement | Satisfaction | Reasoning | Evidence quote | Provider/model |
|---|---:|---|---|---|
| SQL queries with SELECT/JOIN/WHERE for backend testing | 60% | Evidence shows execution of SQL queries for backend data integrity checks, confirming backend testing, but does not mention SELECT, JOINs, or WHERE clauses specifically. | `Executed SQL queries for backend data integrity checks ensuring proper data mapping and transaction logging` | Groq / `openai/gpt-oss-120b` |
| Fundamental SQL queries across MySQL/PostgreSQL/SQL Server | 30% | Evidence indicates the candidate wrote SQL queries, but does not specify fundamental queries nor any listed relational database platforms. | `Executed SQL queries for backend data integrity checks ensuring proper data mapping and transaction logging` | Groq / `openai/gpt-oss-120b` |
| Filtering, sorting, and combining data across tables | 0% | No evidence of filtering, sorting, combining data, or working across multiple tables is provided. | Empty | Groq / `openai/gpt-oss-120b` |
| Strong SQL skills | 20% | Evidence shows the candidate executed SQL queries, indicating some skill, but provides no indication of strong SQL expertise. | `SQL & Data Validation` | Groq / `openai/gpt-oss-120b` |

**Aggregate score:** 27.5 before any preferred-skill contribution.

The important QA result is that the model explicitly refused to infer unsupported query syntax and awarded 0% for the zero-shared-keyword paraphrased requirement.

### Round 3: Gemini model ID corrected to `gemini-3.6-flash`

**Result: Passed through fallback.**

The Gemini model identifier was corrected after a direct API response stated:

```text
This model models/gemini-2.5-flash is no longer available to new users.
Please update your code to use models/gemini-3.6-flash.
```

The endpoint remained:

```text
https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
```

During the validation run, Gemini returned `503 Service Unavailable`. The provider chain correctly failed over to Groq.

Actual Groq output:

| Requirement | Satisfaction | Reasoning | Evidence quote | Provider/model |
|---|---:|---|---|---|
| SQL queries with SELECT/JOIN/WHERE for backend testing | 70% | Evidence shows execution of SQL queries for backend data integrity checks, supporting backend testing, but does not explicitly mention SELECT, JOINs, or WHERE clauses. | `Executed SQL queries for backend data integrity checks ensuring proper data mapping and transaction logging` | Groq / `openai/gpt-oss-120b` |
| Fundamental SQL queries across MySQL/PostgreSQL/SQL Server | 30% | Evidence indicates SQL queries were executed, but provides no proof of writing fundamental queries nor any mention of MySQL, PostgreSQL, or SQL Server. | `Executed SQL queries for backend data integrity checks ensuring proper data mapping and transaction logging` | Groq / `openai/gpt-oss-120b` |
| Filtering, sorting, and combining data across tables | 0% | No evidence of filtering, sorting, or combining data across multiple tables is present. | Empty | Groq / `openai/gpt-oss-120b` |
| Strong SQL skills | 40% | Evidence lists SQL and execution of SQL queries, indicating some SQL ability, but does not demonstrate the depth or strength implied by strong skills. | `SQL & Data Validation` | Groq / `openai/gpt-oss-120b` |

**Aggregate score:** 35.0 before any preferred-skill contribution.

### Round 4: Gemini free-tier model updated to `gemini-3.8-flash`

**Result: Passed through fallback.**

The primary model and free-tier fallback candidates were updated to `gemini-3.8-flash`, `gemini-3.7-flash`, and `gemini-3.5-flash-lite`. During the exact same live validation with the same four requirements and candidate evidence, Gemini returned `503 Service Unavailable`. The provider chain correctly failed over to Groq.

Actual Groq output:

| Requirement | Satisfaction | Reasoning | Evidence quote | Provider/model |
|---|---:|---|---|---|
| SQL queries with SELECT/JOIN/WHERE for backend testing | 30% | Evidence shows generic execution of SQL queries for backend data integrity checks, but does not explicitly mention SELECT, JOINs, or WHERE clauses, nor explicit testing context, so only partial support. | `Executed SQL queries for backend data integrity checks ensuring proper data mapping and transaction logging` | Groq / `openai/gpt-oss-120b` |
| Fundamental SQL queries across MySQL/PostgreSQL/SQL Server | 0% | Evidence does not mention writing fundamental queries nor specify any relational database platforms. | Empty | Groq / `openai/gpt-oss-120b` |
| Filtering, sorting, and combining data across tables | 0% | No evidence of filtering, sorting, or combining data across multiple tables is provided. | Empty | Groq / `openai/gpt-oss-120b` |
| Strong SQL skills | 20% | Evidence only indicates that SQL queries were executed, which suggests some skill but does not substantiate a strong proficiency claim. | `Executed SQL queries for backend data integrity checks ensuring proper data mapping and transaction logging` | Groq / `openai/gpt-oss-120b` |

**Aggregate score:** 12.5 before any preferred-skill contribution.

### Round 5: Gemini 503 exponential backoff

**Result: Exhausted Gemini retries, then fell back to Groq.**

Gemini now retries HTTP 503 responses three times for the same model with delays of 1, 2, and 4 seconds before the provider is marked failed. In the latest exact validation, all four Gemini attempts returned `503 Service Unavailable`, after which Groq answered.

Actual Groq output:

| Requirement | Satisfaction | Reasoning | Evidence quote | Provider/model |
|---|---:|---|---|---|
| SQL queries with SELECT/JOIN/WHERE for backend testing | 40% | Evidence shows execution of SQL queries for backend data integrity checks, but does not specify SELECT, JOINs, or WHERE clauses required by the requirement. | `Executed SQL queries for backend data integrity checks ensuring proper data mapping and transaction logging` | Groq / `openai/gpt-oss-120b` |
| Fundamental SQL queries across MySQL/PostgreSQL/SQL Server | 30% | Evidence indicates SQL queries were executed, but does not demonstrate ability to write fundamental queries nor mention any specific relational database systems. | `Executed SQL queries for backend data integrity checks ensuring proper data mapping and transaction logging` | Groq / `openai/gpt-oss-120b` |
| Filtering, sorting, and combining data across tables | 0% | No evidence of filtering, sorting, combining data, or working across multiple tables is provided. | Empty | Groq / `openai/gpt-oss-120b` |
| Strong SQL skills | 35% | Evidence indicates some SQL usage, but does not demonstrate the depth or breadth implied by strong SQL skills. | `Executed SQL queries for backend data integrity checks ensuring proper data mapping and transaction logging` | Groq / `openai/gpt-oss-120b` |

**Aggregate score:** 26.25 before any preferred-skill contribution.

### Round 6: Certification evidence and permissive semantic gating

Two ranking evidence gaps were corrected. Candidate certifications are now included as
`Certification: ...` evidence. Stage 1 now hard-blocks only when the candidate has no
evidence at all; taxonomy overlap no longer prevents broader or differently phrased
evidence from reaching the semantic judge.

The exact Mohamed Galal CV and Junior QA Engineer 7-required/3-nice-to-have fixture was
not present in this workspace, so that exact pair could not be rerun verbatim. A live
representative Junior-QA validation used the available equivalent evidence:

- `Certification: ISTQB® Certified CTFL V4 certified.`
- `Project description: Database testing`
- `Explicit skill: Selenium`
- `Explicit skill: Jira`

The live response was answered by Groq / `openai/gpt-oss-120b` after Gemini returned 429:

| Requirement | Satisfaction | Result |
|---|---:|---|
| ISTQB Certified Tester Foundation Level (CTFL) | 95% | Certification evidence quoted and explicitly matched |
| SQL (SELECT, JOINs, WHERE clauses) for backend database testing | 20% | Genuine judge reasoning; generic database testing was partial evidence |
| Strong experience with Selenium WebDriver for UI automation | 30% | Selenium was recognized, but WebDriver/UI detail was absent |
| Jira defect tracking and test management | 30% | Jira was recognized, but defect/test-management detail was absent |
| TestNG automated test execution | 0% | No evidence |
| JUnit tests for Java applications | 0% | No evidence |
| Cucumber BDD scenarios | 0% | No evidence |

The named non-regression expectations were preserved in this representative run: absent
TestNG, JUnit, and Cucumber evidence remained at 0%. Exact Mohamed Galal score and the
remaining three JD requirements remain unverified until that CV/JD pair is supplied.

### Validation comparison

| Round | Primary attempted | Actual answering model | Scores | Hallucination status |
|---|---|---|---|---|
| 1 | Qwen 3B via Hugging Face | Qwen 3B | 90%, 90%, 90%, 90% | Failed; overclaimed all clauses |
| 2 | Gemini `gemini-2.5-flash` | Groq GPT-OSS-120B | 60%, 30%, 0%, 20% | Passed; partial and evidence-bound |
| 3 | Gemini `gemini-3.6-flash` | Groq GPT-OSS-120B | 70%, 30%, 0%, 40% | Passed; partial and evidence-bound |
| 4 | Gemini `gemini-3.8-flash` | Groq GPT-OSS-120B | 30%, 0%, 0%, 20% | Passed; partial and evidence-bound |
| 5 | Gemini `gemini-3.8-flash` with 1s/2s/4s retries | Groq GPT-OSS-120B | 40%, 30%, 0%, 35% | Passed; partial and evidence-bound |

Rounds 2 and 3 are consistent in the important behavioral sense:

- The unsupported SELECT/JOIN/WHERE clauses were not treated as explicitly proven.
- The zero-shared-keyword table-operation requirement received 0%.
- Database-platform breadth was not invented.
- The result was graded rather than binary.

The exact percentages varied, which is expected from an LLM judge and confirms that the cache/model/provider identity must remain part of operational traceability.

---

## 4. Current Known Limitation

Gemini's model identifier is no longer a code-level issue.

Evidence:

- Google’s model catalog returned HTTP 200 for the configured key.
- The catalog listed Gemini 2.5 Flash but the direct generation response stated it was unavailable to new users.
- Google's current free-tier availability was confirmed as `gemini-3.8-flash`, `gemini-3.7-flash`, and `gemini-3.5-flash-lite`.
- The provider now uses `gemini-3.8-flash` as the primary model.
- The corrected live call returned `503 Service Unavailable`, not 404.

Gemini has not yet been observed successfully answering as the primary provider because it was unavailable during the test window. The system correctly failed over to Groq. Live confirmation of Gemini as the answering primary provider remains pending a period when Google's endpoint is available for this key.

The successful semantic validation therefore confirms the fallback path and judge quality through Groq, but not successful primary-provider execution through Gemini.

---

## 5. Security Checklist

### Candidate redaction

Confirmed.

Every evidence item passes through:

```python
redacted_item, _ = redact(item)
assert_clean(redacted_item)
```

The provider-chain boundary also calls `assert_clean()` before any provider request.

### Randomized delimiters

Confirmed.

`build_judge_prompt()` uses:

```python
marker = f"CVDATA_{secrets.token_hex(6)}"
```

The same prompt builder is used for Gemini, Groq, and OpenRouter. Therefore all providers receive candidate evidence inside randomized delimiter boundaries.

### Authentication and rate limiting

Confirmed unchanged.

No changes were made to:

- `app/security/auth.py`
- Flask-Limiter configuration in `app/main.py`

### File validation

Confirmed unchanged.

No changes were made to `app/security/file_validator.py`.

### Credential handling

Confirmed.

- Gemini, Groq, and OpenRouter keys load through `config/settings.py`.
- Keys are optional and missing keys skip the corresponding provider.
- Keys are not printed in validation output.
- Gemini uses the `x-goog-api-key` request header.
- Groq and OpenRouter use authorization headers.
- Provider logs include provider/model and error text, never credential values.

### Redis credentials

Confirmed.

Redis configuration is loaded through `config/settings.py` via `REDIS_URL`; no Redis connection string is hardcoded in application logic.

---

## 6. Anti-Overfitting Confirmation

The same four differently worded requirements were tested in two independent live runs using the same candidate evidence and two different answering conditions:

- Round 2: Groq after Gemini 404.
- Round 3: Groq after Gemini 503 with the corrected Gemini 3.6 Flash configuration.
- Round 4: Groq after Gemini 503 with the current free-tier Gemini 3.8 Flash configuration.

The fourth requirement had no useful evidence beyond a generic SQL label. The third requirement deliberately avoided relying on shared taxonomy keywords. Both live Groq runs returned 0% for the table-operation requirement.

This supports that the redesigned behavior is based on evidence and capability interpretation rather than the original keyword/substring mechanism.

Confidence is high that the original deterministic false-positive is fixed. Confidence is moderate that the LLM judge will generalize across all domains because LLM output remains probabilistic. Confidence in Gemini-primary operation is pending a successful availability window.

---

## QA Acceptance Summary

| Area | Status | Notes |
|---|---|---|
| Original substring bug removed | Passed | No raw substring fallback remains in ranking |
| JD text no longer presented as candidate evidence | Passed | Structured evaluations use evidence quotes |
| Taxonomy coarse filter preserved | Passed | Existing canonicalization remains the filter |
| Batched semantic judge | Passed | One batched call for eligible requirements |
| Multi-provider fallback | Passed | Gemini → Groq → OpenRouter order implemented and exercised |
| Gemini 503 retry backoff | Passed | Three same-model retries at 1s, 2s, and 4s before fallback |
| Structured output validation | Passed | Requirement order, count, score bounds, and evidence quotes validated |
| Redis cache | Passed structurally | Redis-first with in-memory fallback; live Redis availability not required for fallback validation |
| Security preservation | Passed | Redaction, assertions, delimiters, auth, limiter, and file validation preserved |
| Anti-overfitting behavior | Passed through two live Groq runs | Unsupported clauses were not accepted as fully proven |
| Gemini primary live confirmation | Pending | Gemini 3.8 Flash exhausted 1s/2s/4s retries with 503s during latest run |

## Final Conclusion

The redesign resolves the original binary keyword false-positive at the architecture level. Matching now evaluates capability evidence through a structured semantic judge, preserves explicit evidence quotes, grades partial support, and traces the actual provider/model used. The live Groq results in Rounds 2 and 3 demonstrate the desired behavior: unsupported SQL syntax and table operations are not silently promoted to complete matches.

The fallback chain also behaved correctly during real Gemini outages. Gemini's model identifier is now the confirmed free-tier `gemini-3.8-flash`, but Gemini-primary success remains pending because the provider returned `503 Service Unavailable` during the latest validation window. That limitation is distinct from the resolved 404/model-identifier issue.
