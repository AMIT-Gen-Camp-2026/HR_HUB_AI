# Frontend Integration Guide — Presentation AI API

> **Who this is for:** Frontend developers integrating with the Presentation AI REST API.  
> Zero backend context assumed. Every claim in this document is based on verified, live API behavior.
>
> **What this is NOT:** `ui/streamlit_app.py` is an internal developer inspector tool. It is not the product. Do not integrate against Streamlit — integrate against the JSON API described here.

---

## 1. Running the Project Locally

### Python version

Python **3.12** is required (pinned in `.python-version`).

### Install

```bash
# From the repo root  (presentation-ai/)
python -m venv .venv

# Windows
.venv\Scripts\pip install -e ".[dev]"

# macOS / Linux
.venv/bin/pip install -e ".[dev]"
```

### Environment variables

Copy `.env.example` to `.env` and fill in the values. The app reads this file at startup — it does **not** crash if keys are missing, but features degrade silently (see below).

| Variable | Required | Description |
|---|---|---|
| `PROVIDER` | Yes | `api` (Gemini, recommended), `stub` (no LLM, instant fake data for UI dev), `hf` (local HuggingFace), `local` (Ollama) |
| `GEMINI_API_KEY` | Yes when `PROVIDER=api` | Gemini API key from aistudio.google.com. Missing key causes every request to fail with `502 CLAIM_EXTRACTION_FAILED`. Set `PROVIDER=stub` to develop without a key. |
| `TAVILY_API_KEY` | Yes when `SEARCH_PROVIDER=tavily` | Web search API key. If missing, objective claims are marked `unclear` with `verification_error: "search_quota_exhausted"`. The request still completes successfully at HTTP 200. |
| `SEARCH_PROVIDER` | No | `tavily` (default), `gemini_grounding`, or `none`. |
| `GEMINI_MODEL` | No | Default: `gemini-3.5-flash-lite`. Used for claim extraction and plausibility. |
| `GEMINI_GROUNDING_MODEL` | No | Default: `gemini-3.6-flash`. Used for web-grounded fact-checking. |
| `API_PORT` | No | Default: `8100`. |
| `LOG_LEVEL` | No | Default: `INFO`. |

### Starting the API server

```bash
# Windows
.venv\Scripts\flask.exe --app app.main:create_app run --port 8100

# macOS / Linux
.venv/bin/flask --app app.main:create_app run --port 8100
```

**Default base URL:** `http://localhost:8100`

### Starting the Streamlit developer dashboard (optional — not the product)

```bash
# Windows
.venv\Scripts\streamlit.exe run ui/streamlit_app.py
```

Opens at `http://localhost:8501`. This dashboard wraps the Flask API for manual developer testing. Your frontend should call the Flask API directly, not this dashboard.

---

## 2. Base URL and Full Endpoint List

**Base URL:** `http://localhost:8100` (configurable via `API_PORT`)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/healthz` | Liveness check. Returns `{"status": "ok"}`. No dependencies on LLM provider. |
| `POST` | `/api/v1/presentation/analyze` | Upload a `.pptx` or `.pdf`, receive a structured analysis report. This is the only functional endpoint. |

---

## 3. Full Request Contract

**Method:** `POST`  
**Path:** `/api/v1/presentation/analyze`  
**Content-Type:** `multipart/form-data`

### Form fields

| Field | Type | Required | Notes |
|---|---|---|---|
| `file` | File | **Yes** | The presentation. Must be `.pptx` or `.pdf`. |
| `applicant_id` | String | No | Optional tracking ID. Not validated, not included in response. |
| `job_id` | String | No | Optional tracking ID. Not validated, not included in response. |

### File constraints

| Constraint | Limit | Error when violated |
|---|---|---|
| Accepted extensions | `.pptx`, `.pdf` | `400 UNSUPPORTED_FORMAT` |
| File must not be empty | — | `400 INVALID_FILE` |
| Magic bytes check | `.pptx` must start with `PK\x03\x04`; `.pdf` must start with `%PDF-` | `400 CORRUPTED_FILE` |
| Maximum file size | **25 MB** (enforced by Flask before the route runs) | `413 FILE_TOO_LARGE` |
| Max PDF pages | 100 (configurable via `PDF_MAX_PAGES` env var) | Pages over limit silently skipped |

### curl examples

```bash
# PPTX
curl -X POST http://localhost:8100/api/v1/presentation/analyze \
  -F "file=@/path/to/presentation.pptx" \
  -F "applicant_id=APPLICANT-42" \
  -F "job_id=JOB-99"

# PDF
curl -X POST http://localhost:8100/api/v1/presentation/analyze \
  -F "file=@/path/to/presentation.pdf"
```

**Success HTTP status:** `200 OK`

---

## 4. Full Response Contract

### Top-level shape

```json
{
  "analysis_id": "ANL-1252b70adb2b",
  "status": "completed",
  "completeness": { ... },
  "presentation": { ... },
  "scores": { ... },
  "summary": { ... },
  "score_evidence": { ... },
  "brief": "...",
  "claims": [ ... ],
  "verifications": [ ... ],
  "issues": [ ... ],
  "suggested_interview_questions": [ ... ]
}
```

### `analysis_id` — string

Unique run identifier. Format: `ANL-` + 12 hex characters. Re-uploading the exact same file bytes returns the same cached result with the same `analysis_id`.

### `status` — `"completed"` | `"partial"`

- `"completed"` — all slides were processed successfully.
- `"partial"` — one or more slides had no extractable text (image-only or corrupt). Analysis still ran on everything it could extract. **This is not an error** — the response body is still valid.

### `completeness` — object

```json
{
  "slides_total": 2,
  "slides_processed": 2,
  "slides_failed": 0,
  "status": "ok",
  "message": null
}
```

| Field | Type | Description |
|---|---|---|
| `slides_total` | int | Total slides/pages in the file. |
| `slides_processed` | int | Slides with extractable text that were analyzed. |
| `slides_failed` | int | Slides with no extractable text (image-only, scanned, etc.). |
| `status` | string | `"ok"`, `"partial"`, or `"no_extractable_content"`. |
| `message` | string or null | Human-readable note when status is not `"ok"`. `null` when status is `"ok"`. |

> **UI note:** If `status == "no_extractable_content"`, the file was all images or scanned pages. Show a warning. Expect `claims` and `verifications` to be empty arrays.

### `presentation` — object

```json
{ "filename": "sample.pptx", "slide_count": 2 }
```

### `scores` — object (all integers, 0–100)

```json
{
  "overall": 60,
  "fact_accuracy": 80,
  "verified_ratio": 0,
  "evidence_coverage": 0,
  "claim_reliability": 80
}
```

| Field | Description |
|---|---|
| `overall` | Composite: 50% Fact Accuracy + 25% Evidence Coverage + 25% Claim Reliability. |
| `fact_accuracy` | Importance-weighted accuracy. Claims with a `verification_error` are excluded from the denominator so infrastructure failures don't penalize the candidate. |
| `verified_ratio` | % of claims confirmed by a concrete math check or external ground source (not just a plausibility heuristic). |
| `evidence_coverage` | % of claims with at least one attached evidence item. |
| `claim_reliability` | Currently mirrors `fact_accuracy`. |

> **Note:** Claims with status `"not_checkable"` are excluded from all score calculations.

### `summary` — object

Counts of each verification status across the entire presentation.

```json
{
  "total_claims": 3,
  "supported": 0,
  "contradicted": 0,
  "project_unsupported": 3,
  "plausibility_flag": 0,
  "unclear": 0,
  "not_checkable": 0
}
```

### `score_evidence` — object or null

Plain-English explanations for four scores. Keys: `"overall"`, `"fact_accuracy"`, `"evidence_coverage"`, `"reliability"`.

```json
{
  "overall": "Overall is 60, combining Fact Accuracy (80), Evidence Coverage (0), and Reliability (80)...",
  "fact_accuracy": "Fact Accuracy is 80: 0 of 3 scoreable claim(s) were CONTRADICTED...",
  "evidence_coverage": "Evidence Coverage is 0 because 0 of 3 scoreable claim(s) have attached concrete evidence; 3 do not.",
  "reliability": "Reliability is 80 because it mirrors the importance-weighted Fact Accuracy calculation..."
}
```

> **UI note:** If `score_evidence` is `null`, skip the score explanation section. Fall back to showing raw numbers only.

### `brief` — string or null

AI-generated paragraph summarizing the presentation content (not the analysis verdicts). Language follows the slide content — English or Arabic.

> **UI note:** If `null` (rare provider failure), fall back to a static placeholder such as *"Analysis complete. See claims below for details."* Never show `null` directly to the user.

### `claims` — array of Claim objects

Every factual claim extracted from the presentation. Matched to `verifications[]` by `claim_id`.

```json
{
  "claim_id": "CLM-001",
  "slide_number": 1,
  "text": "Our CNN model achieved 96% accuracy.",
  "claim_type": "performance",
  "track": "project_specific",
  "importance": "high",
  "subject": "CNN model",
  "property": "accuracy",
  "value": 96.0,
  "unit": "%"
}
```

| Field | Values / Notes |
|---|---|
| `claim_id` | Format `CLM-NNN`. Stable within one analysis run only — not a permanent database ID. |
| `slide_number` | 1-indexed slide / page number where the claim appears. |
| `text` | Extracted claim text as it appeared in the presentation. |
| `claim_type` | One of: `"performance"`, `"dataset"`, `"architecture"`, `"technology"`, `"algorithm"`, `"capability"`, `"business"` |
| `track` | `"objective"` (externally verifiable fact) or `"project_specific"` (self-reported project claim, no external ground truth) |
| `importance` | `"high"`, `"medium"`, or `"low"`. Drives score weighting. |
| `subject`, `property`, `value`, `unit` | Structured extraction of the canonical entity/metric. All may be `null`. |

### `verifications` — array of ClaimVerification objects

One entry per claim. Match by `claim_id`.

```json
{
  "claim_id": "CLM-001",
  "status": "project_unsupported",
  "confidence": 0.95,
  "reason": "An accuracy of 96% for a CNN is entirely plausible depending on dataset complexity...",
  "evidence": [],
  "verification_basis": "plausibility_heuristic_only",
  "verification_error": null
}
```

| Field | Type | Notes |
|---|---|---|
| `claim_id` | string | Matches `claim_id` in `claims[]`. |
| `status` | string | See status table below. |
| `confidence` | float | 0.0–1.0. Model's confidence in the verdict. |
| `reason` | string | Always non-empty. HR-readable explanation of the verdict. |
| `evidence` | array | List of source objects (see below). Empty `[]` is normal. |
| `verification_basis` | string | `"internal_math_check"`, `"external_source"`, `"plausibility_heuristic_only"`, or `"not_applicable"`. |
| `verification_error` | string or null | Non-fatal infrastructure note. `null` is the normal case. See Section 5 for `"search_quota_exhausted"`. |

**Claim status values:**

| Status | Meaning |
|---|---|
| `"supported"` | Verified by internal math check or external evidence. |
| `"contradicted"` | Conflicts with external evidence. |
| `"project_unsupported"` | Self-reported claim; plausible but no external ground truth exists. Normal and expected for project-specific work. |
| `"plausibility_flag"` | Numerically unusual or suspiciously perfect — flagged for human attention during the interview. |
| `"unclear"` | Insufficient confidence to decide. Often caused by search quota exhaustion. |
| `"not_checkable"` | Not a verifiable factual claim (subjective opinion or narrative). Excluded from all scores. |

**Evidence object** (inside `evidence[]` when non-empty):

```json
{
  "source_type": "general_web",
  "source_url": "https://example.com/source",
  "snippet": "Short excerpt or calculation rationale from the source."
}
```

`source_type` values: `"official_documentation"`, `"academic"`, `"trusted_technical"`, `"general_web"`.

### `issues` — array of Issue objects

HR-flagged claims. Only `"contradicted"`, `"plausibility_flag"`, and high-importance `"unclear"` claims appear here. Will be `[]` when no issues were found.

```json
{
  "slide_number": 3,
  "claim_id": "CLM-005",
  "severity": "critical",
  "status": "contradicted",
  "claim_text": "Our model achieved 99.9% accuracy on ImageNet.",
  "correction": "According to the ImageNet leaderboard, state-of-the-art accuracy is approximately 90.88%."
}
```

| Field | Type | Notes |
|---|---|---|
| `slide_number` | int | Slide where the issue was found. |
| `claim_id` | string | Links to `claims[]`. |
| `severity` | string | `"critical"`, `"high"`, `"medium"`, or `"low"`. Computed deterministically. |
| `status` | string | Same status values as `verifications[]`. |
| `claim_text` | string | Full text of the flagged claim. |
| `correction` | string or null | AI-generated suggested correction. Only present for `"contradicted"` claims that have external evidence attached. `null` otherwise. |

**Severity lookup table (deterministic — not AI):**

| Status | Importance | Severity |
|---|---|---|
| contradicted | high | critical |
| contradicted | medium | high |
| contradicted | low | medium |
| plausibility_flag | high | high |
| plausibility_flag | medium | medium |
| plausibility_flag | low | low |
| unclear | high | medium |
| unclear | medium | low |
| unclear | low | low |

### `suggested_interview_questions` — array of InterviewQuestion objects

Deterministically generated follow-up questions for HR interviewers, based on claim type and importance. Will be `[]` only if no claims were extracted at all.

```json
{
  "claim_id": "CLM-001",
  "slide_number": 1,
  "suggested_question": "What was the baseline benchmark and test workload profile used to evaluate 'Our CNN model achieved 96% accuracy.'?"
}
```

---

### Full example response (real, captured from a live test run)

This is the actual response returned when posting `sample.pptx` (a 2-slide ML performance deck), trimmed to 2 claims:

```json
{
  "analysis_id": "ANL-1252b70adb2b",
  "status": "completed",
  "completeness": {
    "slides_total": 2,
    "slides_processed": 2,
    "slides_failed": 0,
    "status": "ok",
    "message": null
  },
  "presentation": { "filename": "sample.pptx", "slide_count": 2 },
  "scores": {
    "overall": 60,
    "fact_accuracy": 80,
    "verified_ratio": 0,
    "evidence_coverage": 0,
    "claim_reliability": 80
  },
  "summary": {
    "total_claims": 3, "supported": 0, "contradicted": 0,
    "project_unsupported": 3, "plausibility_flag": 0, "unclear": 0, "not_checkable": 0
  },
  "score_evidence": {
    "overall": "Overall is 60, combining Fact Accuracy (80), Evidence Coverage (0), and Reliability (80). Across 3 scoreable claim(s), the verdicts include 0 SUPPORTED, 0 CONTRADICTED, 0 UNCLEAR, 0 PLAUSIBILITY_FLAG, and 3 PROJECT_UNSUPPORTED.",
    "fact_accuracy": "Fact Accuracy is 80: 0 of 3 scoreable claim(s) were CONTRADICTED, while 0 were SUPPORTED, 0 were UNCLEAR, 0 were PLAUSIBILITY_FLAG, and 3 were PROJECT_UNSUPPORTED.",
    "evidence_coverage": "Evidence Coverage is 0 because 0 of 3 scoreable claim(s) have attached concrete evidence; 3 do not.",
    "reliability": "Reliability is 80 because it mirrors the importance-weighted Fact Accuracy calculation for the 3 scoreable claim(s), including 0 CONTRADICTED claim(s)."
  },
  "brief": "This two-slide presentation covers machine learning model performance and comparisons. The first slide presents the accuracy of a CNN model, while the second slide displays a table comparing this to the accuracy of Random Forest and SVM models.",
  "claims": [
    {
      "claim_id": "CLM-001", "slide_number": 1,
      "text": "Our CNN model achieved 96% accuracy.",
      "claim_type": "performance", "track": "project_specific", "importance": "high",
      "subject": "CNN model", "property": "accuracy", "value": 96.0, "unit": "%"
    },
    {
      "claim_id": "CLM-002", "slide_number": 2,
      "text": "Random Forest | 95%",
      "claim_type": "performance", "track": "project_specific", "importance": "high",
      "subject": "Random Forest", "property": "accuracy", "value": 95.0, "unit": "%"
    }
  ],
  "verifications": [
    {
      "claim_id": "CLM-001", "status": "project_unsupported", "confidence": 0.95,
      "reason": "An accuracy of 96% for a CNN is entirely plausible depending on dataset complexity.",
      "evidence": [], "verification_basis": "plausibility_heuristic_only", "verification_error": null
    },
    {
      "claim_id": "CLM-002", "status": "project_unsupported", "confidence": 0.95,
      "reason": "A Random Forest accuracy of 95% is a common result for tabular datasets.",
      "evidence": [], "verification_basis": "plausibility_heuristic_only", "verification_error": null
    }
  ],
  "issues": [],
  "suggested_interview_questions": [
    {
      "claim_id": "CLM-001", "slide_number": 1,
      "suggested_question": "What was the baseline benchmark and test workload profile used to evaluate 'Our CNN model achieved 96% accuracy.'?"
    },
    {
      "claim_id": "CLM-002", "slide_number": 2,
      "suggested_question": "What was the baseline benchmark and test workload profile used to evaluate 'Random Forest | 95%'?"
    }
  ]
}
```

---

## 5. Error Responses

All errors follow this shape:

```json
{
  "status": "error",
  "error": { "code": "ERROR_CODE", "message": "Human-readable description." }
}
```

### Complete error table

| HTTP | `error.code` | What triggers it |
|---|---|---|
| 400 | `INVALID_FILE` | No file in request, empty filename, or empty file body |
| 400 | `UNSUPPORTED_FORMAT` | Extension is not `.pptx` or `.pdf` |
| 400 | `CORRUPTED_FILE` | Magic bytes mismatch or corrupt internal structure |
| 413 | `FILE_TOO_LARGE` | File exceeds 25 MB |
| 422 | `EXTRACTION_FAILED` | No slides, or all slides failed text extraction |
| 502 | `CLAIM_EXTRACTION_FAILED` | AI claim extraction call failed (bad API key, quota hit, model unavailable) |
| 502 | `FACT_CHECK_FAILED` | AI fact-check call failed at the pipeline level |
| 500 | `SCORING_FAILED` | Deterministic scoring raised an unexpected exception |
| 500 | `INTERNAL_ERROR` | Unhandled exception — contact the backend team |
| 429 | `DAILY_QUOTA_EXCEEDED` | Gemini API daily request cap was hit |
| 404 | `NOT_FOUND` | Route does not exist |

### Real error response examples (verified from live tests)

```json
// No file — 400
{ "status": "error", "error": { "code": "INVALID_FILE", "message": "No file was provided under the 'file' field." } }

// Wrong extension — 400
{ "status": "error", "error": { "code": "UNSUPPORTED_FORMAT", "message": "Only .pptx and .pdf files are supported." } }

// Bad magic bytes — 400
{ "status": "error", "error": { "code": "CORRUPTED_FILE", "message": "The uploaded file is not a valid PowerPoint archive." } }

// File too large — 413
{ "status": "error", "error": { "code": "FILE_TOO_LARGE", "message": "Uploaded file exceeds the size limit." } }

// Route not found — 404
{ "status": "error", "error": { "code": "NOT_FOUND", "message": "Route not found." } }
```

### `verification_error: "search_quota_exhausted"` — graceful degradation, NOT a failure

When web search is unavailable (quota hit, API key missing, network error), the pipeline degrades per-claim instead of aborting the request. The response is still `200` with a fully valid body.

Affected claims appear in `verifications[]` as:

```json
{
  "status": "unclear",
  "verification_error": "search_quota_exhausted",
  "reason": "Web search verification unavailable (grounding quota exhausted for this account); requires manual review."
}
```

**What your UI should do:**

- Do **not** show a global error banner. The analysis succeeded.
- Optionally show a subtle per-claim indicator: *"Could not verify externally — manual review needed."*
- This is a free-tier infrastructure limitation, not a problem with the candidate's data.

Similarly, `status: "unclear"` without `verification_error` means the AI could not form a confident verdict from available evidence. Treat it as "needs human review", not "system error".

---

## 6. Practical Integration Notes

### Expected response time

| Scenario | Approximate time |
|---|---|
| Small deck (0–5 claims, project_specific only) | 15–30 seconds |
| Medium deck (5–15 mixed claims) | 30–90 seconds |
| Large deck (15–30 claims, many objective / web-searched) | 90–180 seconds |
| Very large deck (30+ slides) | Up to 5 minutes |

**Why it's slow:** An 8-second pacing delay (`gemini_call_pacing_seconds`) sits between consecutive Gemini API calls to stay within free-tier rate limits. Web searches for `"objective"` track claims run in parallel threads, but `"project_specific"` claims are batched in groups of 4 and processed sequentially.

**Frontend recommendations:**
- Show a loading indicator immediately on file submission.
- Add messaging like: *"Analysis typically takes 1–3 minutes for a full-length presentation."*
- Set your HTTP request timeout to **at least 300 seconds** (5 minutes). For very large decks, 600 seconds is safer.

### Result caching

The server caches the last 50 results by SHA-256 hash of the uploaded file bytes. Re-uploading the exact same file returns the cached result instantly (milliseconds, no LLM calls). The cache resets on server restart.

### Authentication

**There is currently no authentication.** Any client that can reach the server can call the API. Do not expose the server on a public network without adding auth at the network layer (reverse proxy, API gateway, etc.).

### Synchronous only — no async / webhook mode

The HTTP connection stays open for the full analysis duration. There is no job queue or webhook callback mechanism. Your frontend must:

1. Set a long HTTP timeout (at least 300 seconds).
2. Show a progress/loading state while waiting.
3. Handle timeout errors gracefully (e.g. *"Analysis timed out — try uploading a shorter presentation."*).

### Concurrency

The Flask development server handles one request at a time. In production, gunicorn provides worker-based concurrency. For local development, avoid submitting multiple files simultaneously.

### `applicant_id` and `job_id` pass-through fields

These optional form fields are accepted and passed to server-side logging only. They do **not** appear in the response body and do **not** affect the analysis output in any way.