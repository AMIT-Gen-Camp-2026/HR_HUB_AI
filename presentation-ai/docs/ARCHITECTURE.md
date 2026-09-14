# Architecture & Developer Integration Guide

This document provides a comprehensive architecture overview, pipeline execution walkthrough, external dependency guide, API reference, and operational constraints for developers integrating with or maintaining the `presentation_ai` service.

---

## Quickstart

Follow these minimal steps to run the service locally from a fresh repository clone:

```bash
# 1. Clone repository & change directory
cd presentation-ai

# 2. Create and activate a Python virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows PowerShell: .venv\Scripts\Activate.ps1

# 3. Install required dependencies
pip install -r requirements.txt

# 4. Create environment configuration (.env)
cat << 'EOF' > .env
PROVIDER=api
GEMINI_API_KEY=your_gemini_api_key_here
TAVILY_API_KEY=your_tavily_api_key_here
SEARCH_PROVIDER=tavily
ENABLE_ACADEMIC_SEARCH=true
CLAIM_EXTRACTION_BATCH_SIZE=4
GEMINI_CALL_PACING_SECONDS=8.0
LOG_LEVEL=INFO
EOF

# 5. Start the Flask JSON API server (runs on port 8100)
flask --app app.main:create_app run --port 8100

# 6. (Optional) In a separate terminal, launch the Streamlit Developer Inspection UI
streamlit run ui/streamlit_app.py
```

To test an analysis call immediately:
```bash
curl -X POST "http://localhost:8100/api/v1/presentation/analyze" \
  -F "file=@/path/to/sample_presentation.pptx" \
  -F "applicant_id=APP-001" \
  -F "job_id=JOB-99"
```

---

## 1. High-Level Architecture & Pipeline Execution Flow

The service consists of two runtime components:
1. **Flask API Layer ([`app/api/routes_presentation.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/api/routes_presentation.py))**: The primary production interface. Exposes REST endpoints for binary PowerPoint upload and returns structured JSON decision-support payloads.
2. **Streamlit UI ([`ui/streamlit_app.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/ui/streamlit_app.py))**: A developer inspection dashboard designed for visually auditing claims, verifications, score breakdowns, and issue corrections.

### Pipeline Stages in Execution Order (`app/pipeline/`)

The analysis workflow is framework-agnostic, modular, and executes sequentially through the following pipeline stages:

```text
[ Binary PPTX ] ──► 1. extract_pptx ──► 2. normalize ──► 3. claim_extraction ──► 4. fact_check (Dispatcher)
                                                                                         │
                             ┌───────────────────────────────────────────────────────────┴──────────────────────────────────────────┐
                             ▼                                                                                                      ▼
               [ Track A: objective ]                                                                                [ Track B: project_specific ]
                 evidence_general                                                                                            plausibility
             (Tavily + OpenAlex search)                                                                                  (Hard Rules + LLM Batch)
                             │                                                                                                      │
                             └───────────────────────────────────────────────────────────┬──────────────────────────────────────────┘
                                                                                         ▼
[ PresentationAnalysisResult ] ◄── 8. run.py ◄── 7. postprocess ◄── 6. report_summary ◄── 5. scoring
```

#### Stage 1: `extract_pptx.py` (Deterministic Extraction)
Parses raw binary `.pptx` bytes using `python-pptx`. Extracts text frames, titles, bullet lists, markdown tables, embedded chart series, and presenter speaker notes. Outputs an `ExtractedPresentation` object containing per-slide `SlideContent` instances and slide counts. If the file is not a valid zip archive, raises `CorruptedFile`.

#### Stage 2: `normalize.py` (Deterministic Normalization)
Cleans and standardizes extracted text across English and Arabic content. Removes non-printable unicode control characters, fixes whitespace formatting, and generates formatted prompt-ready strings via `slide_to_prompt_text()`. Outputs a `NormalizedPresentation` object.

#### Stage 3: `claim_extraction.py` (AI Claim Extraction & Classification)
Extracts verifiable technical claims using Gemini (`gemini-3.5-flash-lite`) and template [`claim_extract.v4.jinja`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/prompts/templates/claim_extract.v4.jinja). Slides are batched in groups (default size `4` per `claim_extraction_batch_size`), with slide contents bounded by `<<<PRESENTATION_CONTENT_START/END>>>` security delimiters. Claims are classified into 7 taxonomy categories (`performance`, `dataset`, `architecture`, `technology`, `algorithm`, `capability`, `business`), tagged with track (`objective` vs `project_specific`), assigned importance (`high`, `medium`, `low`), and extracted with explicit quantitative fields (`subject`, `property`, `value`, `unit`). Outputs `list[Claim]` and `failed_slides`.

#### Stage 4: `fact_check.py` (AI Verification Dispatcher)
Routes each extracted claim to its respective track for verification:
- **Track A (`objective`)**: Routes to `evidence_general.py` for factual claims checkable against general or academic knowledge.
- **Track B (`project_specific`)**: Routes to `plausibility.py` for claims about the applicant's own proprietary work.
Outputs a `list[ClaimVerification]`.

#### Stage 4a: `evidence_general.py` (Track A Grounding & Search Verification)
Executes external web evidence collection concurrently via `ThreadPoolExecutor` using `TavilySearchProvider` (general web) and `SemanticScholarProvider` (OpenAlex academic works). Evaluates claim validity against gathered snippets using `fact_check.v2.jinja` with Gemini. Enforces a strict code-level guardrail: any claim marked `supported` or `contradicted` without a valid evidence URL and a confidence score $\ge 0.75$ is automatically force-downgraded to `unclear`.

#### Stage 4b: `plausibility.py` (Track B Project Plausibility Evaluation)
Evaluates applicant project claims where public web evidence cannot exist. Applies hard deterministic sanity check rules first (e.g. checking for unrealistic 100% accuracy claims or negative latency), followed by batched LLM plausibility reasoning (`verify_batch`) using `plausibility_judgment.v2.jinja` (3–5 claims per call).

#### Stage 5: `scoring.py` (Deterministic Pure Scoring Engine)
A 100% pure deterministic scoring function with zero LLM or network dependencies. Calculates four normalized 0–100 scores:
- `overall`: $0.50 \cdot \text{fact\_accuracy} + 0.25 \cdot \text{evidence\_coverage} + 0.25 \cdot \text{claim\_reliability}$
- `fact_accuracy`: Importance-weighted accuracy ratio across supported vs contradicted claims.
- `evidence_coverage`: Percentage of claims backed by real web evidence or explicit plausibility analysis.
- `claim_reliability`: Ratio of reliable claims weighted by importance and severity.

#### Stage 6: `report_summary.py` (AI Report Synthesis)
Generates an executive technical summary (`brief`) and a human-readable score explanation (`score_evidence`) using `report_summary.v1.jinja`. Synthesizes overall presentation quality and flags major discrepancies.

#### Stage 7: `postprocess.py` (AI Correction Generation & Deterministic Issue Construction)
Generates textual corrections via `correction_generate.v1.jinja` for all claims verified as `contradicted`. Deterministically maps verifications to structured `Issue` records (assigning severity: `critical`, `high`, `medium`, `low`) and compiles `suggested_interview_questions` for technical hiring managers.

#### Stage 8: `run.py` (Pipeline Orchestrator)
Entry point function `run_presentation_analysis()`. Coordinates stages 1 through 7, tracks slide failure metadata (`CompletenessMeta`), manages exception boundaries, and compiles the final `PresentationAnalysisResult` domain model.

---

## 2. External Dependencies

### Google Gemini API
- **Models**:
  - `gemini-3.5-flash-lite`: Primary lightweight completion model (`gemini_model` setting). Used for batched claim extraction, plausibility reasoning, report summary, and correction generation.
  - `gemini-3.6-flash`: Configured grounding model (`gemini_grounding_model` setting).
  - `gemini-embedding-001`: Hosted embedding model (`gemini_embedding_model` setting) used for text vectorization.
- **Quota & Pacing**: Free tier imposes a hard limit of 500 requests per day per project per model (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`). To avoid hitting Requests Per Minute (RPM) limits, process-wide monotonic delay (`gemini_call_pacing_seconds`, default 8.0s) is enforced in [`app/providers/api_provider.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/providers/api_provider.py).

### OpenAlex API (Academic Search)
- **Endpoint**: `https://api.openalex.org/works`
- **Purpose**: Provides academic publication search for Track A objective claims without requiring API keys or restricted domain emails.
- **Client Implementation**: [`app/providers/search/semantic_scholar_provider.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/providers/search/semantic_scholar_provider.py) (class name `SemanticScholarProvider` retained for interface consistency).
- **Features**: Requests identify via a polite pool `User-Agent` (`presentation-ai (mailto:youssefkhaled855@gmail.com)`), respect rate limiting, and reconstruct full-text abstracts from inverted position dictionaries (`abstract_inverted_index`).

### Tavily API (General Web Search)
- **Purpose**: General web search engine for verifying objective non-academic claims.
- **Client Implementation**: [`app/providers/search/tavily_provider.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/providers/search/tavily_provider.py). Requires `TAVILY_API_KEY`.

---

## 3. How to Run Locally & Configuration

### Environment Variables (`.env`)

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `PROVIDER` | string | `"stub"` | Provider backend: `"api"` (Gemini), `"stub"` (offline test), `"hf"`, `"local"`. |
| `GEMINI_API_KEY` | string | `""` | Google Gemini API key (required when `PROVIDER=api`). |
| `SEARCH_PROVIDER` | string | `"tavily"` | Grounding provider: `"tavily"`, `"gemini_grounding"`, `"none"`. |
| `TAVILY_API_KEY` | string | `""` | Tavily search API key (required when `SEARCH_PROVIDER=tavily`). |
| `ENABLE_ACADEMIC_SEARCH` | bool | `true` | Enables OpenAlex academic paper searching alongside web search. |
| `ACADEMIC_MAX_RESULTS` | int | `3` | Maximum academic papers retrieved per claim query. |
| `CLAIM_EXTRACTION_BATCH_SIZE` | int | `4` | Number of slides processed per claim extraction LLM call. |
| `GEMINI_CALL_PACING_SECONDS` | float | `8.0` | Minimum delay in seconds between consecutive Gemini API requests. |
| `API_PORT` | int | `8100` | Port for the Flask application server. |

### Commands

**Start Flask API**:
```bash
flask --app app.main:create_app run --port 8100
```
*Alternatively*: `python -m app.main`

**Start Streamlit Inspection Dashboard**:
```bash
streamlit run ui/streamlit_app.py
```

---

## 4. API Reference Surface

All endpoints are registered under `app/api/`.

### 1. Health Check
- **HTTP Method**: `GET`
- **Path**: `/healthz`
- **Request Body**: None
- **Response Format (`200 OK`)**:
  ```json
  {
    "status": "ok"
  }
  ```

---

### 2. Presentation Analysis Endpoint
- **HTTP Method**: `POST`
- **Path**: `/api/v1/presentation/analyze`
- **Headers**: `Content-Type: multipart/form-data`
- **Request Form Parameters**:
  - `file` (binary, **required**): PowerPoint file (`.pptx`). Max size 25MB (`MAX_CONTENT_LENGTH`). Must have valid ZIP magic header bytes (`PK\x03\x04`).
  - `applicant_id` (string, *optional*): Identifier of the candidate.
  - `job_id` (string, *optional*): Job opening identifier.

- **Response Body (`200 OK`)**:
  ```json
  {
    "analysis_id": "ANL-a1b2c3d4e5f6",
    "status": "completed",
    "completeness": {
      "slides_total": 10,
      "slides_processed": 10,
      "slides_failed": 0
    },
    "presentation": {
      "filename": "applicant_deck.pptx",
      "slide_count": 10
    },
    "scores": {
      "overall": 85,
      "fact_accuracy": 90,
      "evidence_coverage": 80,
      "claim_reliability": 85
    },
    "summary": {
      "total_claims": 12,
      "supported": 8,
      "contradicted": 1,
      "unclear": 3
    },
    "score_evidence": {
      "fact_accuracy": "High accuracy across technical stack claims.",
      "evidence_coverage": "80% of claims verified against external sources."
    },
    "brief": "The presentation demonstrates solid foundational architecture...",
    "claims": [
      {
        "claim_id": "CLM-001",
        "slide_number": 2,
        "text": "PostgreSQL supports native JSONB indexing.",
        "claim_type": "technology",
        "track": "objective",
        "importance": "high",
        "subject": "PostgreSQL",
        "property": "json_support",
        "value": null,
        "unit": null
      }
    ],
    "verifications": [
      {
        "claim_id": "CLM-001",
        "status": "supported",
        "confidence": 0.95,
        "reason": "Official PostgreSQL documentation verifies GIN indexing on JSONB types.",
        "evidence": [
          {
            "title": "PostgreSQL Documentation",
            "url": "https://www.postgresql.org/docs/current/datatype-json.html",
            "snippet": "JSON data types can be indexed using GIN...",
            "source_type": "general_web"
          }
        ],
        "verification_basis": "web_grounded",
        "verification_error": null
      }
    ],
    "issues": [],
    "suggested_interview_questions": [
      {
        "slide_number": 2,
        "claim_id": "CLM-001",
        "suggested_question": "Can you explain how GIN indexes optimize JSONB queries in PostgreSQL?"
      }
    ]
  }
  ```

- **Example `curl` Request**:
  ```bash
  curl -X POST "http://localhost:8100/api/v1/presentation/analyze" \
    -F "file=@/home/user/presentations/demo_deck.pptx" \
    -F "applicant_id=CANDIDATE-8821" \
    -F "job_id=REQ-402"
  ```

---

## 5. Known Operational Constraints & Integrator Guidance

### 1. Free-Tier Daily Quota Cap (`DAILY_QUOTA_EXCEEDED`)
- **Constraint**: Google Gemini free-tier imposes a strict daily cap of 500 requests per day per project per model (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`).
- **Error Response Shape (`429 Too Many Requests`)**:
  ```json
  {
    "status": "error",
    "error": {
      "code": "DAILY_QUOTA_EXCEEDED",
      "message": "Gemini free-tier daily/rate quota exceeded. Try again later or switch to a paid tier."
    }
  }
  ```
- **Integrator Action**: External clients calling `/api/v1/presentation/analyze` **must** check HTTP status `429` and `error.code == "DAILY_QUOTA_EXCEEDED"`. When received, clients should display a clear notice to end users to retry after quota reset or upgrade to a paid Gemini API tier.

### 2. Throughput & Batch Tuning
- Integrators can tune processing throughput and API usage by adjusting configuration settings in `.env`:
  - `CLAIM_EXTRACTION_BATCH_SIZE` (default `4`): Increasing batch size reduces total LLM calls per presentation but increases prompt token footprint per request.
  - `GEMINI_CALL_PACING_SECONDS` (default `8.0`): Adjusts inter-call sleep duration to balance processing speed against Gemini's Requests Per Minute (RPM) ceiling.

### 3. Verification Guardrail Policy
- Downstream systems consuming `verifications` must note that Track A (`objective`) claims will never return `supported` or `contradicted` without valid `evidence` sources and confidence $\ge 0.75$. Claims failing this threshold are automatically reported as `unclear` with `verification_basis: "plausibility_heuristic_only"`.
