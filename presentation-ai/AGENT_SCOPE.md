# AGENT_SCOPE.md — What the Agent Does and Does Not Do

This document provides a precise, technical definition of the **Presentation AI** agent's capabilities, boundaries, pipeline stages, trust boundaries, external dependencies, configuration parameters, and output contracts for engineers, product managers, and integration partners.

---

## 1. What the Agent Is

**Presentation AI** is an automated decision-support pipeline that analyzes job applicant presentation slides (`.pptx` or `.pdf` files) submitted prior to a technical interview or project demo. The system ingests binary presentation bytes, extracts textual content and embedded structures, identifies verifiable technical and project claims, verifies objective facts against web search and academic databases, evaluates project-specific claims for contextual plausibility, computes importance-weighted factual accuracy scores, and returns a single, structured [`PresentationAnalysisResult`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/schemas/presentation.py#L152-L172) JSON payload. 

The AI agent's role is strictly limited to semantics-dependent tasks: extracting factual claims from unstructured slide content, classifying claim tracks and types, judging plausibility or verifying objective claims against search snippets, generating short corrections for contradicted facts, and composing an English executive brief. All structural file parsing, text normalization, arithmetic verification, hard-rule enforcement, score calculations, severity assignments, and interview question templating are performed deterministically by Python code. The system does not make hiring decisions; it generates diagnostic evidence for HR reviewers.

---

## 2. What the Agent Does — Stage by Stage

The analysis pipeline is orchestrated by [`run_presentation_analysis()`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/run.py#L31-L138) in [`app/pipeline/run.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/run.py). Stages execute in the following sequential order:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ Stage 1: Extraction (Deterministic)                                                   │
│ app/pipeline/extract_pptx.py & app/pipeline/extract_pdf.py                            │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │ ExtractedPresentation
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ Stage 2: Normalization (Deterministic)                                                 │
│ app/pipeline/normalize.py                                                              │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │ ExtractedPresentation (Normalized)
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ Stage 3: Claim Extraction & Classification (AI)                                        │
│ app/pipeline/claim_extraction.py (Prompt: claim_extract.v4.jinja)                     │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │ list[Claim]
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ Stage 4: Fact Verification & Plausibility (AI + Deterministic Dispatcher)              │
│ app/pipeline/fact_check.py -> evidence_general.py & plausibility.py                   │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │ list[ClaimVerification]
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ Stage 5: Scoring Computation (Deterministic)                                           │
│ app/pipeline/scoring.py                                                                │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │ Scores
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ Stage 6: Report Summary & Brief Generation (AI + Deterministic)                       │
│ app/pipeline/report_summary.py (Prompt: report_summary.v1.jinja)                      │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │ score_evidence, brief
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ Stage 7: Postprocessing & Question Assembly (AI + Deterministic)                      │
│ app/pipeline/postprocess.py (Prompt: correction_generate.v1.jinja)                    │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │ corrections, issues, interview_questions
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ Final Output Assembly: PresentationAnalysisResult JSON                                 │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

### Stage 1: File Parsing & Content Extraction
* **Module Ownership:** [`app/pipeline/extract_pptx.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/extract_pptx.py) (`extract()`) and [`app/pipeline/extract_pdf.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/extract_pdf.py) (`extract_pdf()`).
* **AI Role:** None (100% deterministic).
* **Deterministic Role:** Reads raw binary bytes (`.pptx` via `python-pptx`, `.pdf` via `PyMuPDF`). Extracts title text, body text frames, pipe-rendered table rows (`cell | cell`), chart titles/series, and speaker notes per slide. Tracks per-slide exceptions without failing the entire presentation.
* **Input $\rightarrow$ Output:** `content: bytes` $\rightarrow$ `ExtractedPresentation(slide_count: int, slides: list[SlideContent], failed_slide_numbers: list[int])`.
* **Model & Prompt:** None.

---

### Stage 2: Content Normalization
* **Module Ownership:** [`app/pipeline/normalize.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/normalize.py) (`normalize()`).
* **AI Role:** None (100% deterministic).
* **Deterministic Role:** Applies Unicode NFKC normalization, canonicalizes visually identical Arabic code points (e.g. Alef Maksura $\rightarrow$ Yeh, Persian Kaf $\rightarrow$ Arabic Kaf), strips duplicate lines per slide, and cleans whitespace without removing numbers, units, or negations.
* **Input $\rightarrow$ Output:** `ExtractedPresentation` $\rightarrow$ `ExtractedPresentation` (mutated with normalized text elements).
* **Model & Prompt:** None.

---

### Stage 3: Claim Extraction & Classification
* **Module Ownership:** [`app/pipeline/claim_extraction.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/claim_extraction.py) (`extract_claims()`).
* **AI Role:** LLM analyzes slide text blocks to identify factual claims, classifying each into:
  1. `track`: `"objective"` (public general knowledge) or `"project_specific"` (applicant's own project/dataset/metrics).
  2. `claim_type`: 1 of 7 types (`performance`, `dataset`, `architecture`, `technology`, `algorithm`, `capability`, `business`).
  3. `importance`: `"high"`, `"medium"`, or `"low"`.
  4. Structured quad: `subject`, `property`, `value`, `unit` (when quantitative).
* **Deterministic Role:** Chunks slides into batches (size controlled by `settings.claim_extraction_batch_size`, default `4`), enforces inter-call RPM pacing sleep delays, parses JSON array output into `RawClaimOutput`, coerces unknown types/tracks to safe defaults (`"capability"`, `"project_specific"`), canonicalizes property names via [`canonicalize_property()`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/taxonomy/canonicalize.py), assigns unique sequential IDs (`CLM-001`, `CLM-002`), and tracks failed slide batches.
* **Input $\rightarrow$ Output:** `slides: list[SlideContent]` $\rightarrow$ `tuple[claims: list[Claim], failed_slides: list[int]]`.
* **Model & Prompt:** Configured Gemini model (`settings.gemini_model`, default `"gemini-3.5-flash-lite"`) via `provider.complete()`. Uses prompt template [`claim_extract.v4.jinja`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/prompts/templates/claim_extract.v4.jinja) with response schema `list[RawClaimOutput]`.

---

### Stage 4: Fact Verification & Plausibility (Dispatcher)
* **Module Ownership:** [`app/pipeline/fact_check.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/fact_check.py) (`verify_claims()`), routing to Track A ([`app/pipeline/evidence_general.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/evidence_general.py)) or Track B ([`app/pipeline/plausibility.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/plausibility.py)).

#### Track A: Objective Claims ([`evidence_general.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/evidence_general.py))
* **AI Role:** Evaluates an objective claim against web search snippets or Google Search Grounding to assign `status` (`"supported"`, `"contradicted"`, `"unclear"`), `confidence` ($0.0 \le c \le 1.0$), and a grounding `reason`.
* **Deterministic Role:** 
  1. Fetches external evidence snippets in parallel via Tavily API and Academic Search (ArXiv & Semantic Scholar).
  2. If search returns no sources or quota is exhausted, invokes [`quota_fallback()`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/evidence_general.py#L42-L51) returning `status="unclear"` and `verification_error="search_quota_exhausted"`.
  3. **Code Enforced Trust Boundary:** If LLM returns `"supported"` or `"contradicted"` but evidence sources are empty OR `confidence < 0.75` (`MIN_CONFIDENCE_FOR_VERDICT`), the code force-downgrades `status` to `"unclear"`.
* **Input $\rightarrow$ Output:** `claim: Claim` $\rightarrow$ `ClaimVerification`.
* **Model & Prompt:** 
  * If `search_provider == "tavily"`: Prompt [`fact_check.v2.jinja`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/prompts/templates/fact_check.v2.jinja) with model `settings.gemini_model`.
  * If `search_provider == "gemini_grounding"`: Prompt [`fact_check.v1.jinja`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/prompts/templates/fact_check.v1.jinja) with model `settings.gemini_grounding_model` (`"gemini-3.6-flash"`) and `use_grounding=True`.

#### Track B: Project-Specific Claims ([`plausibility.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/plausibility.py))
* **AI Role:** Evaluates contextual plausibility for claims that pass deterministic checks, flagging implausible metric/dataset claims (`flagged: bool`, `reason: str`, `confidence: float`).
* **Deterministic Role:**
  1. [`check_internal_math_consistency()`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/plausibility.py#L50-L113): Executes regex math checks verifying count/total = percentage (e.g., `4/25 = 16%`). If math matches $\rightarrow$ `status="supported"`, `verification_basis="internal_math_check"`. If math fails $\rightarrow$ `status="plausibility_flag"`, `verification_basis="internal_math_check"`. (Bypasses LLM).
  2. [`hard_rules()`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/plausibility.py#L115-L141): Checks if reported accuracy/precision/recall/F1/R2 metrics are $\ge 99.5\%$ (`_ROUND_THRESHOLD`), or if performance/dataset claims lack subject and property. If triggered $\rightarrow$ `status="plausibility_flag"`, `verification_basis="plausibility_heuristic_only"`. (Bypasses LLM).
  3. Batches remaining claims into chunks of 4 (`BATCH_SIZE`) for LLM evaluation. On batch failure, falls back to single-claim LLM calls.
* **Input $\rightarrow$ Output:** `list[tuple[Claim, str]]` $\rightarrow$ `list[ClaimVerification]`.
* **Model & Prompt:** Model `settings.gemini_model` via `provider.complete()`. Prompt: [`plausibility_judgment.v2.jinja`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/prompts/templates/plausibility_judgment.v2.jinja) with response schema `list[RawPlausibilityItem]`.

---

### Stage 5: Scoring Computation
* **Module Ownership:** [`app/pipeline/scoring.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/scoring.py) (`compute_scores()`).
* **AI Role:** None (100% deterministic pure function).
* **Deterministic Role:** Computes importance-weighted precision scores for all scoreable claims (excluding `not_checkable` claims and claims with `verification_error`):
  * **Weights:** `high` = 3, `medium` = 2, `low` = 1.
  * **Status Values:** `supported` = 1.00, `project_unsupported` = 0.80, `unclear` = 0.50, `plausibility_flag` = 0.30, `contradicted` = 0.00.
  * **Fact Accuracy (`fact_accuracy`):** Weighted sum of status values divided by total weight of eligible claims.
  * **Verified Ratio (`verified_ratio`):** Percentage of eligible claims verified by concrete math checks or external ground sources.
  * **Evidence Coverage (`evidence_coverage`):** Percentage of claims with attached evidence (1.5x multiplier for academic sources).
  * **Claim Reliability (`claim_reliability`):** Mirrors `fact_accuracy`.
  * **Overall (`overall`):** $0.50 \times \text{fact\_accuracy} + 0.25 \times \text{evidence\_coverage} + 0.25 \times \text{claim\_reliability}$.
* **Input $\rightarrow$ Output:** `claims: list[Claim]`, `verifications: list[ClaimVerification]` $\rightarrow$ `Scores`.
* **Model & Prompt:** None.

---

### Stage 6: Report Summary & Brief Generation
* **Module Ownership:** [`app/pipeline/report_summary.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/report_summary.py) (`generate_report_summary()`).
* **AI Role:** Generates a 3-5 sentence English executive presentation brief summarizing deck topic, structure, and tone directly from extracted slide text.
* **Deterministic Role:**
  * [`build_score_evidence()`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/report_summary.py#L109-L116): Formats human-readable score rationale strings in English or Arabic (based on claim language signal `_is_arabic()`).
  * [`_fallback_brief()`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/report_summary.py#L130-L137): Generates a deterministic English fallback overview if LLM generation fails or context is empty.
* **Input $\rightarrow$ Output:** `claims`, `verifications`, `scores`, `slides` $\rightarrow$ `tuple[score_evidence: dict[str, str], brief: str]`.
* **Model & Prompt:** Model `settings.gemini_model` via `provider.complete(temperature=0.0)`. Prompt: [`report_summary.v1.jinja`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/prompts/templates/report_summary.v1.jinja).

---

### Stage 7: Postprocessing (Corrections, Issues, Interview Questions)
* **Module Ownership:** [`app/pipeline/postprocess.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/postprocess.py).
* **AI Role:** [`generate_correction()`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/postprocess.py#L50-L79): Invoked **ONLY** for claims with `status == "contradicted"` and non-empty `evidence`. Generates a single neutral correction sentence strictly from the attached evidence snippet. If LLM fails or evidence lacks a clear value, returns exact fallback `"No verified value was found in the available evidence."`.
* **Deterministic Role:**
  * [`assign_severity()`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/postprocess.py#L46-L47): Maps `(status, importance)` to issue severity (`critical`, `high`, `medium`, `low`) via a static lookup table.
  * [`build_issues()`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/postprocess.py#L82-L108): Assembles `Issue` instances for claims with non-null severity.
  * [`build_interview_questions()`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/postprocess.py#L193-L272): Generates probing follow-up interview questions using static template matching by `claim_type`. Automatically filters out low-value logistics/environment claims (`_is_low_value_logistics()`), prioritizes `plausibility_flag` claims first, and enforces template deduplication limits.
* **Input $\rightarrow$ Output:** `claims`, `verifications`, `corrections` $\rightarrow$ `corrections: dict[str, str]`, `issues: list[Issue]`, `interview_questions: list[InterviewQuestion]`.
* **Model & Prompt:** Model `settings.gemini_model`. Prompt: [`correction_generate.v1.jinja`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/prompts/templates/correction_generate.v1.jinja).

---

## 3. What the Agent Explicitly Does NOT Do

1. **Does NOT make hiring decisions:** The agent is an objective decision-support tool for HR. Final candidate acceptance or rejection rests entirely with human reviewers ([`docs/DECISIONS.md`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/docs/DECISIONS.md) section 1).
2. **Does NOT perform audio, video, or candidate image analysis:** Input is strictly presentation slides (`.pptx` / `.pdf`). Spoken audio and video demo evaluation is out of scope (handled separately by Demo AI) ([`docs/DECISIONS.md`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/docs/DECISIONS.md) section 2).
3. **Does NOT fact-check `project_specific` claims on the public web:** Claims about an applicant's internal project, dataset size, or custom architecture cannot be verified against public web sources. They are evaluated via arithmetic checks, hard rules, or contextual plausibility heuristics ([`docs/DECISIONS.md`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/docs/DECISIONS.md) section 3).
4. **Does NOT extract non-checkable filler content:** [`claim_extract.v4.jinja`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/prompts/templates/claim_extract.v4.jinja) explicitly filters out greetings, agenda/section titles, "Thank You" / Q&A slides, subjective opinions, and vague statements.
5. **Does NOT assign issue severity using AI:** Issue severity (`critical`, `high`, `medium`, `low`) is calculated deterministically in [`assign_severity()`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/postprocess.py#L46-L47) via a fixed matrix lookup.
6. **Does NOT generate interview questions using AI:** Question generation in [`build_interview_questions()`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/postprocess.py#L193-L272) uses deterministic template selection, regex string formatting, and frequency capping.
7. **Does NOT invent ungrounded corrections or external facts:** [`generate_correction()`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/postprocess.py#L50-L79) is forbidden from inventing facts outside the provided snippet, returning `"No verified value was found in the available evidence."` if no clear value exists.
8. **Streamlit UI is NOT the production product:** [`ui/streamlit_app.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/ui/streamlit_app.py) is a developer inspection dashboard for visual auditing during development. The production product is the JSON REST API ([`routes_presentation.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/api/routes_presentation.py)).

---

## 4. Trust Boundaries & Hardcoded Rules

The system enforces deterministic overrides whenever AI output is ungrounded or when deterministic checks provide higher certainty:

| Rule Name | File & Function Location | Deterministic Rule Description | Rationale / Decision Reference |
| :--- | :--- | :--- | :--- |
| **Grounding & Confidence Downgrade** | [`app/pipeline/evidence_general.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/evidence_general.py) $\rightarrow$ `verify()` (L151–L153) | If LLM returns `status == "supported"` or `"contradicted"`, but `evidence_sources` is empty OR `confidence < 0.75` (`MIN_CONFIDENCE_FOR_VERDICT`), `status` is force-downgraded to `"unclear"`. | Never trust self-reported LLM verdicts without verifiable grounding snippets ([`docs/DECISIONS.md`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/docs/DECISIONS.md) section 9). |
| **Internal Math Check Override** | [`app/pipeline/plausibility.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/plausibility.py) $\rightarrow$ `check_internal_math_consistency()` (L50–L113) | Executes regex math verification (`count/total = percentage`). If valid $\rightarrow$ `status="supported"`, `verification_basis="internal_math_check"`. If invalid $\rightarrow$ `status="plausibility_flag"`. Bypasses LLM. | Deterministic math is 100% reliable, eliminating LLM arithmetic hallucination and saving tokens. |
| **Plausibility Hard Rules** | [`app/pipeline/plausibility.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/plausibility.py) $\rightarrow$ `hard_rules()` (L115–L141) | Reported metrics (`accuracy`, `precision`, `recall`, `f1_score`, `r2_score`) $\ge 99.5\%$ (`_ROUND_THRESHOLD`), or performance/dataset claims lacking subject and property, automatically trigger `status="plausibility_flag"`. | Suspicious perfection and contextless claims require mandatory HR review ([`docs/DECISIONS.md`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/docs/DECISIONS.md) section 5). |
| **Claim Schema Coercion** | [`app/pipeline/claim_extraction.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/claim_extraction.py) $\rightarrow$ `_coerce_claim()` (L56–L105) | Unrecognized `claim_type` defaults to `"capability"`; unrecognized `track` defaults to `"project_specific"`; unrecognized `importance` defaults to `"medium"`. | Guarantees strict Pydantic enum compliance and defaults to under-claiming verifiability. |
| **Grounding Quota Fallback** | [`app/pipeline/evidence_general.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/evidence_general.py) $\rightarrow$ `quota_fallback()` (L42–L51) | If search tools hit rate limits (HTTP 429), verification returns `status="unclear"` with `verification_error="search_quota_exhausted"`. | Explicitly separates infrastructure/quota limits from candidate content accuracy ([`docs/DECISIONS.md`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/docs/DECISIONS.md) section 18). |

---

## 5. External Dependencies the Agent Relies On

| Service Name | Purpose | Calling Pipeline Stage | Graceful Degradation / Failure Behavior |
| :--- | :--- | :--- | :--- |
| **Google Gemini API** (`google.genai` SDK in [`api_provider.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/providers/api_provider.py)) | Primary LLM backend for claim extraction, fact-checking, plausibility, briefs, and corrections. | `claim_extraction.py`, `evidence_general.py`, `plausibility.py`, `report_summary.py`, `postprocess.py` | If daily quota is exceeded, raises `DailyQuotaExceeded` (HTTP 429). Server errors (503) retry up to 2 times with backoff, then degrade gracefully to fallback strings or `unclear` statuses. |
| **Tavily Web Search API** ([`tavily_provider.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/providers/search/tavily_provider.py)) | Fetches general web search snippets for Track A objective claims. | `evidence_general.py` (`_gather_sources()`) | Catches network/API exceptions and returns an empty list. `evidence_general.py` triggers `quota_fallback()`, returning `status="unclear"` and `verification_error="search_quota_exhausted"`. |
| **Academic Search APIs** (ArXiv [`arxiv_provider.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/providers/search/arxiv_provider.py) & Semantic Scholar [`semantic_scholar_provider.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/providers/search/semantic_scholar_provider.py)) | Fetches supplemental academic papers for technical claims when `enable_academic_search == True`. | `evidence_general.py` (`_gather_sources()` via `ThreadPoolExecutor`) | Exceptions are caught silently and return an empty list without interrupting Tavily web search or pipeline execution. |

---

## 6. Configuration Surface

Behavioral settings defined in [`config/settings.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/config/settings.py) that alter agent behavior, model routing, or verdict generation:

| Setting Name | Type | Default Value | Behavioral Effect |
| :--- | :--- | :--- | :--- |
| `provider` | `Literal["api", "hf", "local", "stub"]` | `"stub"` | Selects the active LLM backend provider adapter. |
| `gemini_api_key` | `str` | `""` | Gemini API credentials key. |
| `gemini_model` | `str` | `"gemini-3.5-flash-lite"` | Primary Gemini model used for claim extraction, plausibility, briefs, and corrections. |
| `gemini_grounding_model` | `str` | `"gemini-3.6-flash"` | Model used when Google Search Grounding tool is enabled. |
| `search_provider` | `Literal["gemini_grounding", "tavily", "none"]` | `"tavily"` | Determines search grounding backend for Track A claims. |
| `tavily_api_key` | `str` | `""` | Tavily Web Search API key. |
| `tavily_max_results` | `int` | `5` | Maximum web search snippets retrieved per claim. |
| `enable_academic_search` | `bool` | `True` | Feature flag enabling parallel ArXiv and Semantic Scholar searches. |
| `academic_max_results` | `int` | `3` | Maximum academic snippets retrieved per claim. |
| `pdf_ocr_enabled` | `bool` | `False` | Feature flag enabling OCR processing on scanned/image-only PDF pages. |
| `pdf_max_pages` | `int` | `100` | Maximum page limit for uploaded PDF presentations. |
| `gemini_call_pacing_seconds` | `float` | `8.0` | Process-wide pacing sleep delay between consecutive Gemini API calls to respect free-tier RPM limits. |
| `claim_batch_size` | `int` | `5` | Maximum number of claims evaluated per plausibility LLM call chunk. |
| `claim_extraction_batch_size` | `int` | `4` | Maximum number of slides processed per claim extraction LLM call chunk. |

---

## 7. What a Single Run Produces

Every call to `POST /api/v1/presentation/analyze` returns a single JSON object adhering strictly to the [`PresentationAnalysisResult`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/schemas/presentation.py#L152-L172) Pydantic schema:

| Top-Level JSON Key | Content Summary | Producer | Presence |
| :--- | :--- | :--- | :--- |
| `analysis_id` | Unique analysis run identifier (e.g. `"ANL-a1b2c3d4e5f6"`). | Deterministic (`run.py`) | Always present |
| `status` | Analysis execution status (`"completed"` or `"partial"`). | Deterministic (`run.py`) | Always present |
| `completeness` | Object containing `slides_total`, `slides_processed`, `slides_failed`. | Deterministic (`run.py`) | Always present |
| `presentation` | Object containing `filename` and `slide_count`. | Deterministic (`run.py`) | Always present |
| `scores` | Object containing integer scores (0–100): `overall`, `fact_accuracy`, `verified_ratio`, `evidence_coverage`, `claim_reliability`. | Deterministic (`scoring.py`) | Always present |
| `summary` | Object containing claim verdict counts (`total_claims`, `supported`, `contradicted`, `project_unsupported`, `plausibility_flag`, `unclear`, `not_checkable`). | Deterministic (`run.py`) | Always present |
| `score_evidence` | Map of score keys to human-readable rationale strings. | Deterministic (`report_summary.py`) | Present (or `null`) |
| `brief` | 3–5 sentence English executive presentation brief. | AI (`report_summary.py`) with deterministic fallback | Present (or `null`) |
| `claims` | Array of extracted [`Claim`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/schemas/presentation.py#L54-L68) objects (`claim_id`, `slide_number`, `text`, `claim_type`, `track`, `importance`, `subject`, `property`, `value`, `unit`). | AI (`claim_extraction.py`), coerced by deterministic code | Always present (can be `[]`) |
| `verifications` | Array of [`ClaimVerification`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/schemas/presentation.py#L70-L90) objects (`claim_id`, `status`, `confidence`, `reason`, `evidence`, `verification_basis`, `verification_error`). | AI + Deterministic (`fact_check.py`) | Always present (can be `[]`) |
| `issues` | Array of [`Issue`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/schemas/presentation.py#L99-L106) objects (`slide_number`, `claim_id`, `severity`, `status`, `claim_text`, `correction`). | Deterministic (`postprocess.py`), with AI-generated correction for contradicted claims | Always present (can be `[]`) |
| `suggested_interview_questions` | Array of [`InterviewQuestion`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/schemas/presentation.py#L131-L137) objects (`slide_number`, `claim_id`, `suggested_question`). | Deterministic (`postprocess.py`) | Always present (can be `[]`) |
