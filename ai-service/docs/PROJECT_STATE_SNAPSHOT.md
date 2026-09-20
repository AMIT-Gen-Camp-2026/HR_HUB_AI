# Project State Snapshot — AMIT AI Service (CV-Ranking)

**Document Generated:** 2026-09-17 10:48 UTC+3  
**Target Repository:** `HR_HUB_AI / ai-service`  
**Purpose:** Authoritative, code-verified snapshot of the current state of the AI service for technical review and onboarding. Every claim in this document is cited with exact file paths and line numbers verified against active repository code.

---

## 1. Project Overview

- **Role in HR_HUB_AI:** An isolated AI microservice dedicated to CV document parsing, structured skill/experience extraction, taxonomy canonicalization, and candidate-to-job-description capability ranking. Operates independently as a containerized REST service to isolate AI model latency, quota management, and extraction dependencies from the main full-stack application ([`ai-service/README.md:L5-7`](file:///d:/github%20project/HR_HUB_AI/ai-service/README.md#L5-L7)).
- **Core Technology Stack:**
  - **Runtime & Language:** Python `>=3.11` (verified running on Python `3.14.3` in local virtual environment) ([`ai-service/pyproject.toml:L19`](file:///d:/github%20project/HR_HUB_AI/ai-service/pyproject.toml#L19)).
  - **Web Framework:** Flask `3.0.3` (WSGI server using Gunicorn `23.0+` for production container execution) ([`ai-service/pyproject.toml:L23-25`](file:///d:/github%20project/HR_HUB_AI/ai-service/pyproject.toml#L23-L25), [`requirements.txt:L2`](file:///d:/github%20project/HR_HUB_AI/requirements.txt#L2)).
  - **Data Validation & Schemas:** Pydantic `2.13.4` and Pydantic-Settings `2.6+` ([`ai-service/pyproject.toml:L26-27`](file:///d:/github%20project/HR_HUB_AI/ai-service/pyproject.toml#L26-L27), [`requirements.txt:L4,L13`](file:///d:/github%20project/HR_HUB_AI/requirements.txt#L4#L13)).
  - **Document Ingestion:** `pdfplumber 0.11.4` (PDF text extraction) and `python-docx 1.1.2` (DOCX extraction) ([`ai-service/pyproject.toml:L32-33`](file:///d:/github%20project/HR_HUB_AI/ai-service/pyproject.toml#L32-L33), [`requirements.txt:L5-6`](file:///d:/github%20project/HR_HUB_AI/requirements.txt#L5-L6)).
  - **Text & Language Utilities:** `rapidfuzz 3.10+` and `pyarabic 0.6.15` ([`ai-service/pyproject.toml:L35-36`](file:///d:/github%20project/HR_HUB_AI/ai-service/pyproject.toml#L35-L36)).
  - **Model & Provider Clients:** `huggingface-hub 1.28.0` (Inference API for extraction) and `httpx 0.27.0` (OpenAI-compatible & Gemini REST calls for LLM judges and embeddings) ([`ai-service/pyproject.toml:L38-39`](file:///d:/github%20project/HR_HUB_AI/ai-service/pyproject.toml#L38-L39), [`requirements.txt:L7,L23`](file:///d:/github%20project/HR_HUB_AI/requirements.txt#L7#L23)).
  - **Rate Limiting:** `Flask-Limiter 3.8.0` (process-local in-memory storage) ([`ai-service/pyproject.toml:L24`](file:///d:/github%20project/HR_HUB_AI/ai-service/pyproject.toml#L24), [`requirements.txt:L10`](file:///d:/github%20project/HR_HUB_AI/requirements.txt#L10)).
  - **Interactive UI:** Streamlit `1.55.0` ([`requirements.txt:L9`](file:///d:/github%20project/HR_HUB_AI/requirements.txt#L9)).
  - **External Cache / Queue Infrastructure:** **None**. Zero external dependencies (Redis removed; operates 100% process-local).

---

## 2. API Surface

The API surface contains exactly two active endpoints defined in [`app/main.py`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/main.py):

### A. `GET /api/v1/health`
- **Location:** [`app/main.py:L53-55`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/main.py#L53-L55)
- **HTTP Method:** `GET`
- **Request Format:** No payload required.
- **Authentication:** **Open / Unprotected**. Does not apply `@require_api_key` to support Docker container health checks and uptime probes ([`app/main.py:L53`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/main.py#L53), [`docs/DECISIONS.md:L188-189`](file:///d:/github%20project/HR_HUB_AI/ai-service/docs/DECISIONS.md#L188-L189)).
- **Response:** `{"status": "ok"}` with HTTP `200 OK`.

### B. `POST /api/v1/cv/evaluate`
- **Location:** [`app/main.py:L58-173`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/main.py#L58-L173)
- **HTTP Method:** `POST`
- **Request Format:** `multipart/form-data` with two required fields:
  1. `file` (File binary): Uploaded `.pdf` or `.docx` file (enforces max size 10MB, extension check, and binary magic-number validation via [`app/security/file_validator.py:L31-36`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/security/file_validator.py#L31-L36)).
  2. `job_description` (Form field string): JSON-encoded payload parsing into [`app/schemas/cv.py:JobDescription`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/schemas/cv.py#L90-L98) containing `title`, `required_skills` (list of strings), `nice_to_have_skills` (list of strings), and `min_experience_years` (optional integer).
- **Authentication Mechanism:**
  - Enforced via the `@require_api_key` decorator defined in [`app/security/auth.py:L24-53`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/security/auth.py#L24-L53).
  - Inspects the incoming request header: `X-API-Key`.
  - Secure verification: Uses `hmac.compare_digest(provided, config.AI_SERVICE_API_KEY)` ([`app/security/auth.py:L49`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/security/auth.py#L49)).
  - **Fail-Open Policy:** If `AI_SERVICE_API_KEY` is not set in `.env` (empty string), the endpoint permits calls with a single logged warning to facilitate local dev/testing without credentials ([`app/security/auth.py:L37-45`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/security/auth.py#L37-L45)). If set, any missing or mismatched key returns HTTP `401 Unauthorized` (`{"success": False, "error": "Missing or invalid API key."}`).
- **Rate Limiting:** `@limiter.limit("10 per hour")` ([`app/main.py:L60`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/main.py#L60)). Global default app rate limit is `30 per hour` ([`app/main.py:L50`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/main.py#L50)).
- **Response Structure:**
  ```json
  {
    "success": true,
    "cv": { ... },
    "ranking": { ... },
    "extraction_status": "SUCCESS",
    "extraction_metadata": { ... }
  }
  ```

### C. Endpoints Removed / Merged
- The historical two-step endpoints (`POST /api/v1/cv/extract` and `POST /api/v1/rank`) were **permanently removed and merged** into `POST /api/v1/cv/evaluate` to eliminate redundant network roundtrips and avoid client-side payload re-submission ([`docs/DECISIONS.md:L174-181`](file:///d:/github%20project/HR_HUB_AI/ai-service/docs/DECISIONS.md#L174-L181)).

---

## 3. Scoring Pipeline

### A. Current Version & Constants
- **`scoring_version` String:** `"weighted-70-20-10-v1"` ([`app/pipeline/ranking.py:L442`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/pipeline/ranking.py#L442)).
- **Taxonomy & Judge Versions:** `TAXONOMY_VERSION = "2026.09"`, `JUDGE_PROMPT_VERSION = "ranking-judge-v1"` ([`app/pipeline/ranking.py:L21-22`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/pipeline/ranking.py#L21-L22)).
- **Weight Constants:**
  - `REQUIRED_WEIGHT = 0.8` ([`app/pipeline/ranking.py:L19`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/pipeline/ranking.py#L19))
  - `NICE_TO_HAVE_WEIGHT = 0.2` ([`app/pipeline/ranking.py:L20`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/pipeline/ranking.py#L20))
  - `HARD_SKILL_WEIGHT = 1.0` ([`app/pipeline/ranking.py:L23`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/pipeline/ranking.py#L23))
  - `SEMANTIC_WEIGHT = 0.0` ([`app/pipeline/ranking.py:L24`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/pipeline/ranking.py#L24))

### B. Exact 70 / 20 / 10 Formula & Calculation
The authoritative evaluation score is computed in [`app/pipeline/ranking.py:L360-418`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/pipeline/ranking.py#L360-L418):

1. **Individual Skill Evaluation:**
   $$\text{final\_skill\_score} = \text{round}(\text{satisfaction\_percent} \times \text{source\_multiplier}, 2)$$
   Where `satisfaction_percent` $\in [0.0, 100.0]$ is returned by the LLM judge, and `source_multiplier` is determined by the taxonomy tier.
2. **Required Skills Component (70%):**
   $$\text{required\_component} = \overline{\text{final\_skill\_score}}_{\text{required}} \times 0.70$$
   (Line 401: `required_component = (req_final_avg or 0.0) * 0.70`)
3. **Nice-to-Have Skills Component (20%):**
   $$\text{nice\_to\_have\_component} = \overline{\text{final\_skill\_score}}_{\text{nice\_to\_have}} \times 0.20$$
   (Line 405: `nice_to_have_component = (pref_final_avg or 0.0) * 0.20`)
4. **Experience Duration Component (10%):**
   - Candidate total years computed via `calculate_total_experience_years(candidate.experience)` with date parsing and overlap merging ([`app/pipeline/ranking.py:L408,L95-156`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/pipeline/ranking.py#L408#L95-L156)).
   - If `min_experience_years` is `None` or `<= 0`: $\text{experience\_ratio} = 1.0$.
   - If `min_experience_years > 0`: $\text{experience\_ratio} = \min\left(\frac{\text{candidate\_total\_years}}{\text{min\_experience\_years}}, 1.0\right)$.
   - $\text{experience\_component} = \text{experience\_ratio} \times 0.10$ (Line 414).
5. **Total Final Score:**
   $$\text{score} = \text{round}((\text{required\_component} + \text{nice\_to\_have\_component} + \text{experience\_component}) \times 100, 2)$$

### C. Breakdown Output Object
The `breakdown` dictionary returned inside `ranking` contains exactly the following 16 fields ([`app/pipeline/ranking.py:L431-448`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/pipeline/ranking.py#L431-L448)):
1. `required_skills_total`: `int` (total count of required skills in JD)
2. `required_satisfaction_average`: `float | None` (unweighted average satisfaction ratio $[0.0, 1.0]$)
3. `nice_to_have_skills_total`: `int` (total count of nice-to-have skills in JD)
4. `nice_to_have_satisfaction_average`: `float | None` (unweighted average satisfaction ratio $[0.0, 1.0]$)
5. `preferred_bonus`: `float` (legacy bonus calculation, rounded to 4 decimals)
6. `hard_skill_score`: `float` (legacy hard skill score, rounded to 4 decimals)
7. `hard_skill_weight`: `float` (constant `1.0`)
8. `semantic_weight`: `float` (constant `0.0`)
9. `taxonomy_version`: `str` (`"2026.09"`)
10. `judge_prompt_version`: `str` (`"ranking-judge-v1"`)
11. `scoring_version`: `str` (`"weighted-70-20-10-v1"`)
12. `required_component`: `float` (rounded to 4 decimals)
13. `nice_to_have_component`: `float` (rounded to 4 decimals)
14. `experience_component`: `float` (rounded to 4 decimals)
15. `candidate_total_years`: `float` (parsed total years of candidate experience)
16. `experience_ratio`: `float` (ratio of actual to required experience, rounded to 4 decimals)

---

## 4. Taxonomy State

### A. Skill Count & File
- **Source File:** [`app/skills/taxonomy.yaml`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/skills/taxonomy.yaml)
- **Verified Skill Count:** **327 canonical skills** (verified via `yaml.safe_load`).

### B. Source Multiplier Tiers
Defined in [`app/pipeline/ranking.py:L299-324`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/pipeline/ranking.py#L299-L324):
- **`1.0` (Explicit Skill Match):** The candidate's `cv.skills` explicitly list the canonical skill (`requirement_skill_ids & explicit_ids`).
- **`0.80` (Parent / Encompassed Match):** The candidate possesses an ancestor skill in `cv.skills` whose `includes:` hierarchy encompasses the requirement (`requirement_skill_ids & parent_skill_ids`).
- **`0.50` (Narrative / Project Evidence):** The skill is extracted only from experience/project narrative text (`requirement_skill_ids & narrative_ids`).
- **`0.50` (Default / Taxonomy-Unresolvable):** Requirement is not found or not mapped in the candidate's canonical skill sets.

### C. Taxonomy Schema Structure & Relationships
Each skill in [`taxonomy.yaml`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/skills/taxonomy.yaml) supports:
- `id`: Canonical identifier string (e.g. `skill.fastapi`, `skill.machine_learning`).
- `name`: Display string (e.g. `FastAPI`, `Machine Learning`).
- `aliases`: List of variant spellings, abbreviations, or Arabic/English transliterations.
- `includes`: List of subskill canonical IDs encompassed by this parent skill.
- **Hierarchical Engine (`app/skills/canonicalize.py`):**
  - `_hierarchy_lookup()`: Transitive graph mapping parent IDs to all recursive subskills ([`canonicalize.py:L75-95`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/skills/canonicalize.py#L75-L95)).
  - `_reverse_hierarchy_lookup()`: Inverted graph mapping subskills to all ancestor parent IDs ([`canonicalize.py:L99-106`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/skills/canonicalize.py#L99-L106)).
  - Functions: `get_encompassed_subskills()`, `get_parent_skills()`, `is_parent_of()`, `is_hierarchy_parent()`.

---

## 5. Redaction / PII Handling

All PII handling and sanitization is isolated in [`app/pipeline/redact.py`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/pipeline/redact.py):

### A. Extraction & Redaction Functions
1. **`extract_contact_info(text: str) -> dict[str, str | None]`** ([`redact.py:L37-56`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/pipeline/redact.py#L37-L56)):
   - Extracts email and phone numbers directly using deterministic regex *prior* to redaction.
   - Values are preserved and re-inserted into `cv.personal_info.email` and `cv.personal_info.phone` after model extraction completes ([`app/pipeline/run.py:L166-191,L251-254`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/pipeline/run.py#L166-L191#L251-L254)).
2. **`redact(text: str) -> tuple[str, int]`** ([`redact.py:L16-27`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/pipeline/redact.py#L16-L27)):
   - Replaces all matching PII patterns with literal replacement tokens.
3. **`assert_clean(payload: str) -> None`** ([`redact.py:L30-35`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/pipeline/redact.py#L30-L35)):
   - Outbound safety guard. Scans the final built prompt string for raw `NATIONAL_ID`, `EMAIL`, or `PHONE` patterns and raises `AssertionError` if any raw identifier is present before dispatching to external model APIs.

### B. Verbatim Placeholder Tokens
Quoted directly from [`app/pipeline/redact.py:L19-24`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/pipeline/redact.py#L19-L24):
| PII Pattern | Regex Expression | Literal Replacement Token |
|---|---|---|
| **National ID** | `\b[23]\d{13}\b` (14 digits starting with 2 or 3) | `"[NATIONAL_ID]"` |
| **Email Address** | `[\w.+-]+@[\w-]+\.[\w.-]+` | `"[EMAIL]"` |
| **Phone Number** | `(?:\+?20\|0)?1[0125]\d{8}\b` (Egyptian mobile) | `"[PHONE]"` |
| **Any Long Digits** | `\b\d{10,}\b` (10 or more digits) | `"[NUMBER]"` |

---

## 6. LLM Judge Configuration

Implemented in [`app/providers/judge_provider.py`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/providers/judge_provider.py) and configured via [`config/settings.py`](file:///d:/github%20project/HR_HUB_AI/ai-service/config/settings.py):

### A. Provider Chain & Pinned Models
The judge chain executes in sequential priority order based on available API keys ([`judge_provider.py:L229-252`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/providers/judge_provider.py#L229-L252)):

| Priority | Provider Name | Implementation Class | Default Pinned Model String | Settings Config Key |
|---|---|---|---|---|
| **1 (Primary)** | `gemini` | `GeminiJudgeProvider` | `"gemini-3.6-flash"` | `GEMINI_JUDGE_MODEL` |
| **2 (Fallback)** | `groq` | `OpenAICompatibleJudgeProvider` | `"openai/gpt-oss-120b"` | `GROQ_JUDGE_MODEL` |
| **3 (Fallback)** | `openrouter` | `OpenAICompatibleJudgeProvider` | `"meta-llama/llama-3.3-70b-instruct:free"` | `OPENROUTER_JUDGE_MODEL` |

### B. Error Handling, Retries & Fallback Logic
1. **Transient Error Retries:**
   - **Gemini (`GeminiJudgeProvider`):** Retries HTTP `503 Service Unavailable` on the same model with exponential backoff delays of `1s` and `2s` (`GEMINI_RETRY_DELAYS = (1, 2)`) ([`judge_provider.py:L164,L203-219`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/providers/judge_provider.py#L164#L203-L219)).
   - **Groq & OpenRouter (`OpenAICompatibleJudgeProvider`):** Retries HTTP `429 Too Many Requests` and `503 Service Unavailable` with delays of `1s`, `2s`, and `4s` (`RETRY_DELAYS = (1, 2, 4)`) ([`judge_provider.py:L93,L135-154`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/providers/judge_provider.py#L93#L135-L154)).
2. **Sequential Provider Fallback:**
   - If a provider exhausts retries or returns unparseable output, `_query_single_batch()` catches `JudgeProviderError`, logs a warning, and immediately attempts the next provider in `configured_judge_chain()` ([`judge_provider.py:L258-272`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/providers/judge_provider.py#L258-L272)).
3. **Payload Batching:**
   - Requirement lists exceeding `10` items are batched into chunks of `10` with a `1.0s` sleep between batches to avoid HTTP 413 / 503 token limit overflows ([`judge_provider.py:L282-307`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/providers/judge_provider.py#L282-L307)).
4. **Evidence Quote Validation:**
   - If the model returns an `evidence_quote` that does not match the candidate's actual text, it is normalized to `""` rather than failing the evaluation ([`judge_provider.py:L75-80`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/providers/judge_provider.py#L75-L80)).

---

## 7. Test Suite Status

- **Execution Timestamp:** 2026-09-17 10:45 UTC+3
- **Test Result:** **80 passed, 1 warning in 15.14s** (100% pass rate, 0 failures, 0 errors).
- **Code Coverage:** **73.21% total coverage** (meets and exceeds enforced threshold `fail_under = 49.0%` in [`pyproject.toml:L94`](file:///d:/github%20project/HR_HUB_AI/ai-service/pyproject.toml#L94)).
- **Flask-Limiter Warning (Expected):**
  `UserWarning: Using the in-memory storage for tracking rate limits as no storage was explicitly specified.`

### Test Files Inventory
- **Unit Tests (`ai-service/tests/unit/`):**
  1. `test_canonicalize.py`: Taxonomy lookup, alias normalization, and hierarchical includes.
  2. `test_embeddings.py`: Diagnostic embeddings provider isolation.
  3. `test_extraction_snapshot.py`: In-memory `_snapshot_cache` TTL, key hashing, and LRU eviction.
  4. `test_extraction_status.py`: Classification of empty vs populated CV schemas.
  5. `test_hf_provider.py`: Hugging Face model chain fallback and error handling.
  6. `test_judge_provider.py`: Multi-provider judge execution, retries, model pinning, and failover.
  7. `test_ranking.py`: 70/20/10 scoring, date parsing, experience calculation, and multiplier tiers.
  8. `test_redaction.py`: PII regex replacements, placeholders, and `assert_clean()`.
  9. `test_redaction_integration.py`: End-to-end prompt sanitization.
- **Integration Tests (`ai-service/tests/integration/`):**
  1. `test_auth.py`: `X-API-Key` enforcement, open `/health`, and fail-open behavior.
  2. `test_rank_endpoint.py`: End-to-end multipart `/api/v1/cv/evaluate` route integration.

---

## 8. Known Issues / Open Items

1. **Multi-Worker Rate Limiting & Cache Isolation:**
   - `Flask-Limiter`, `_snapshot_cache`, and `_ranking_cache` are process-local (`OrderedDict`). When deploying under Gunicorn with multiple worker processes (`--workers 2`), memory is isolated per worker process rather than globally shared across workers ([`docs/DECISIONS.md:L166-170`](file:///d:/github%20project/HR_HUB_AI/ai-service/docs/DECISIONS.md#L166-L170)).
2. **Diagnostic-Only Semantic Fit:**
   - `SEMANTIC_WEIGHT` is locked at `0.0` in [`app/pipeline/ranking.py:L24`](file:///d:/github%20project/HR_HUB_AI/ai-service/app/pipeline/ranking.py#L24). Semantic embeddings (`semantic_fit`) do not affect candidate ranking scores ([`docs/DECISIONS.md:L217-231`](file:///d:/github%20project/HR_HUB_AI/ai-service/docs/DECISIONS.md#L217-L231)).
3. **Eval Runner Logging Hook:**
   - `eval/runners/run_ranking.py:L109` contains an un-wired hook comment: `# TODO: log this run to MLflow (eval/README.md rule 5) - not wired yet`.
   - `eval/runners/run_extraction.py:L36` contains: `# TODO(sprint-2): run the pipeline over each row and compute:`.

---

## 9. Recent Changes Not Yet Documented in Legacy Guides

1. **Complete Redis Removal:**
   - Deleted `app/cache/cache_backend.py` and `app/cache/`.
   - Removed `redis>=5.0` dependency from `pyproject.toml` and `requirements.txt`.
   - Removed `redis:` service and `depends_on: redis` from `docker-compose.yml`.
   - Removed `REDIS_URL` setting from `config/settings.py`.
   - Restored process-local in-memory `_snapshot_cache` and `_ranking_cache` in `app/pipeline/run.py` using `OrderedDict` with `SNAPSHOT_TTL_SECONDS = 3600.0` and `SNAPSHOT_MAX_ENTRIES = 128`.
2. **LLM Capability Judge Integration:**
   - Added `app/providers/judge_provider.py` with multi-provider chain (Gemini -> Groq -> OpenRouter), retry logic, batching, and quote sanitization.
3. **70/20/10 Weighted Scoring Implementation:**
   - Added experience date parser (`_parse_date_string`) handling ongoing roles and diverse date formats.
   - Updated `breakdown` dictionary to export all 16 evaluation and component metrics.
4. **Hierarchical Taxonomy Expansion:**
   - Expanded `app/skills/taxonomy.yaml` to 327 canonical skills with `includes:` parent-child relationships and transitive lookups in `app/skills/canonicalize.py`.
