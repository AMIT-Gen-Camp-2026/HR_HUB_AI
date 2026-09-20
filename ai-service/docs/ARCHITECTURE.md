# Architecture & Technical Design

## 1. System Overview

The **AMIT AI Service** is a Python-based backend service for CV parsing, candidate data extraction, and capability ranking against Job Descriptions. The service operates via a deterministic pipeline combining rule-based PII redaction, regex-based taxonomy resolution, structured LLM extraction, and multi-provider semantic evaluation.

```
+-------------+      +------------------+      +--------------------+      +--------------------+
|  CV Upload  | ---> | File Validation  | ---> |  Text Extraction   | ---> | PII Redaction &    |
| (PDF/DOCX)  |      |  (Magic Bytes)   |      | (pdfplumber/docx)  |      |   Normalization    |
+-------------+      +------------------+      +--------------------+      +--------------------+
                                                                                     |
                                                                                     v
+-------------+      +------------------+      +--------------------+      +--------------------+
| Final Score | <--- |  70/20/10 Score  | <--- |   Semantic Judge   | <--- | Taxonomy Hierarchy |
|  & Analysis |      |   Calculation    |      | (Gemini / Fallback)|      |  & Source Multipl. |
+-------------+      +------------------+      +--------------------+      +--------------------+
```

---

## 2. End-to-End Pipeline Stages

### Stage 1: File Upload & Security Validation
- **Location:** `app/security/file_validator.py`, `app/main.py`
- **Operations:**
  - Enforces `MAX_CONTENT_LENGTH = 10 * 1024 * 1024` (10MB) via Flask configuration.
  - Extension whitelist check: `.pdf`, `.docx` (`validate_extension`).
  - Magic bytes header inspection (`validate_file_content`):
    - PDF: verifies leading `%PDF` bytes (`header.startswith(b"%PDF")`).
    - DOCX: verifies leading ZIP header bytes `\x50\x4B\x03\x04` (`header.startswith(b"PK\x03\x04")`).

### Stage 2: Text Extraction & Normalization
- **Location:** `app/pipeline/extract_text_pdf.py`, `app/pipeline/extract_text_docx.py`, `app/pipeline/normalize.py`
- **Operations:**
  - PDF: extracts text using `pdfplumber` with `x_tolerance=1` (`extract_text_from_pdf`).
  - DOCX: extracts text from paragraph elements and table cell elements using `python-docx` (`extract_text_from_docx`).
  - Normalization via `clean_cv_text()`:
    - Applies `unicodedata.normalize("NFKC", raw_text)`.
    - Strips control characters `[\x00-\x08\x0B\x0C\x0E-\x1F\x7F\u200e\u200f\u202a-\u202e\u2066-\u2069]`.
    - Collapses whitespace (`[ \t]+` $\rightarrow$ `" "`, `\n{3,}` $\rightarrow$ `"\n\n"`).
    - Truncates text exceeding `MAX_TEXT_LENGTH = 20000` characters (`text = text[:MAX_TEXT_LENGTH]`).

### Stage 3: Contact Extraction & PII Redaction
- **Location:** `app/pipeline/redact.py`, `app/pipeline/run.py`
- **Operations:**
  - Pre-redaction metadata extraction: `extract_contact_info()` uses regex to extract the first matching email and Egyptian mobile number (`(?:\+?20|0)?1[0125]\d{8}\b`) to populate `CVSchema.personal_info` locally before redaction.
  - Text redaction (`redact()`):
    - National ID (`\b[23]\d{13}\b`) $\rightarrow$ `[NATIONAL_ID]`
    - Email (`[\w.+-]+@[\w-]+\.[\w.-]+`) $\rightarrow$ `[EMAIL]`
    - Phone (`(?:\+?20|0)?1[0125]\d{8}\b`) $\rightarrow$ `[PHONE]`
    - Long digit sequences (`\b\d{10,}\b`) $\rightarrow$ `[NUMBER]`
  - Outbound assertion: `assert_clean(payload)` checks for unredacted `NATIONAL_ID`, `EMAIL`, or `PHONE` patterns and raises `AssertionError` if any match is detected.

### Stage 4: Structured Data Extraction (`CVSchema`)
- **Location:** `app/pipeline/run.py`, `app/providers/hf_provider.py`, `app/prompts/registry.py`
- **Operations:**
  - Checks extraction cache using SHA-256 key (`_snapshot_key`) derived from document text hash, prompt version, schema version, taxonomy version, and model chain.
  - Delimits redacted text inside per-request randomized tokens (`<<<CVDATA_<hex>_START>>> ... <<<CVDATA_<hex>_END>>>`).
  - Calls HuggingFace Inference API with model chain:
    1. Primary: `Qwen/Qwen2.5-3B-Instruct` (provider: `featherless-ai`, timeout: `60s`)
    2. Fallback: `mistralai/Mistral-7B-Instruct-v0.2` (provider: `featherless-ai`, timeout: `60s`)
  - Recovers explicit taxonomy skills via regex matching (`extract_explicit_skills`) against `app/skills/taxonomy.yaml`.
  - Assembles and validates output against `CVSchema`.

### Stage 5: Deterministic Taxonomy Hierarchy & Multiplier Calculation
- **Location:** `app/skills/canonicalize.py`, `app/pipeline/ranking.py`
- **Operations:**
  - Maps skills to canonical taxonomy IDs with exact matching, alias matching, and RapidFuzz WRatio matching (`FUZZY_THRESHOLD = 92`).
  - Computes transitive subskill closures from `includes:` lists in `taxonomy.yaml` via graph traversal (`_hierarchy_lookup()`).
  - Builds candidate signal sets (`_candidate_taxonomy_id_sets`):
    - `explicit_ids`: canonical IDs from `candidate.skills`, `candidate.inferred_skills`, `candidate.certifications`.
    - `narrative_ids`: canonical IDs from `candidate.projects` and `candidate.experience`.
    - `parent_skill_ids`: union of all subskills encompassed by `explicit_ids` (`get_encompassed_skills_for_ids`).
  - Requirement skill extraction (`_extract_requirement_skill_ids`): filters out hierarchy parent IDs matched via substring unless the entire requirement string directly canonicalizes to that parent ID.
  - Assigns 4-tier source multiplier (`_calculate_source_multiplier`):
    - **1.0 (Direct Explicit Match):** `requirement_skill_ids & explicit_ids` is non-empty.
    - **0.80 (Hierarchical Parent Match):** `requirement_skill_ids & parent_skill_ids` is non-empty.
    - **0.50 (Narrative Match):** `requirement_skill_ids & narrative_ids` is non-empty.
    - **0.50 (Fallback / Unresolvable):** Requirement not found in taxonomy or candidate signals.

### Stage 6: Multi-Provider LLM Capability Judge
- **Location:** `app/providers/judge_provider.py`, `app/prompts/registry.py`
- **Operations:**
  - Batches all JD requirements into a single structured evaluation prompt.
  - 4-Tier capability judge rubric:
    - **90–100%:** Direct evidence of material operations.
    - **50–75%:** Broader domain logical coverage.
    - **1–49%:** Vague, incidental, or weak partial evidence.
    - **0%:** Absent / irrelevant evidence.
  - Provider failover chain (`configured_judge_chain()`):
    1. **Primary: Google Gemini**
       - Model: `gemini-3.8-flash` (pinned, timeout: `60s`, temperature: `0.0`).
       - Retry: 503 errors trigger backoff retries at `1s`, `2s`, `4s` on the same model.
       - Failover: 404 errors or exhausted 503 retries raise `JudgeProviderError` to move to the next provider.
    2. **Secondary: Groq**
       - Model: `openai/gpt-oss-120b` (base URL: `https://api.groq.com/openai/v1`, timeout: `60s`, temperature: `0.0`).
    3. **Tertiary: OpenRouter**
       - Model: `meta-llama/llama-3.3-70b-instruct:free` (base URL: `https://openrouter.ai/api/v1`, timeout: `60s`, temperature: `0.0`).

### Stage 7: 70 / 20 / 10 Score Calculation
- **Location:** `app/pipeline/ranking.py`
- **Operations:**
  - Individual skill score: $\text{final\_skill\_score} = \text{round}(\text{satisfaction\_percent} \times \text{source\_multiplier}, 2)$
  - Required component (70%): $\text{required\_component} = \overline{\text{final\_skill\_score}}_{\text{required}} \times 0.70$
  - Nice-to-have component (20%): $\text{nice\_to\_have\_component} = \overline{\text{final\_skill\_score}}_{\text{nice\_to\_have}} \times 0.20$
  - Experience component (10%):
    - Total years computed from parsed start/end dates across all role entries (`calculate_total_experience_years`).
    - If `min_experience_years <= 0` or `None`: $\text{experience\_ratio} = 1.0$ (no division by zero).
    - If `min_experience_years > 0`: $\text{experience\_ratio} = \min\left( \frac{\text{candidate\_total\_years}}{\text{min\_experience\_years}}, 1.0 \right)$
    - $\text{experience\_component} = \text{experience\_ratio} \times 0.10$
  - Final score: $\text{score} = \text{round}((\text{required\_component} + \text{nice\_to\_have\_component} + \text{experience\_component}) \times 100, 2)$

### Stage 8: Process-Local In-Memory Caching
- **Location:** `app/pipeline/run.py`
- **Operations:**
  - Fast process-local in-memory LRU cache (`OrderedDict`) for CV extraction snapshots and ranking evaluations.
  - Automatic TTL expiration (`SNAPSHOT_TTL_SECONDS = 3600` / `CACHE_TTL_SECONDS = 3600`) and LRU eviction when size exceeds `max_entries=128`.
  - Snapshot cache key: SHA-256 hash of cleaned text, prompt version, schema version, taxonomy version, and extraction model chain.
  - Ranking cache key: SHA-256 hash of candidate JSON, job description JSON, judge prompt version, taxonomy version, and judge model chain.

---

## 3. Provider Variance & Hierarchy Scope

- **LLM Judge Variance:** While temperature is set to `0.0`, semantic judging across different LLM providers (Gemini vs Groq vs OpenRouter) may exhibit minor score variations due to differences in model weights, tokenizers, and reasoning styles.
- **Hierarchy Scope:** Hierarchical skill coverage is structured strictly in `taxonomy.yaml`. Broad parent skills (such as `Machine Learning`) cover standard foundational tabular algorithms, while specialized domains (`Deep Learning`) are isolated to prevent false-positive over-matching.
