# Recent Changes (Changelog)

This document tracks technical updates, API modifications, architectural shifts, and resilience enhancements in the `presentation_ai` codebase.

---

## [2026-09-14] - Academic Evidence Search Migration, Batched Extraction & Free-Tier Quota Resilience

### 1. External Search Evidence & OpenAlex Integration
- **What Changed**: Replaced Gemini's native built-in Google Search tool (`google_search`) with external web grounding powered by **Tavily** (`TavilySearchProvider`) for general web evidence and **OpenAlex** (`SemanticScholarProvider`) for academic literature search.
- **Why**: Gemini native grounding calls (`types.GenerateContentConfig(tools=[{"google_search": {}}])`) were blocked account-wide on the Gemini API free tier, returning continuous `429 RESOURCE_EXHAUSTED` errors regardless of model choice (`gemini-3.5-flash-lite` or `gemini-3.6-flash`). Switching to external search providers decoupled web grounding from Gemini's tool invocation quota.
- **OpenAlex Usage & Implementation**:
  - OpenAlex (`https://api.openalex.org/works`) is a free, open academic paper catalog used to search scientific publications and verify research claims without API key requirements or free-domain email restrictions.
  - The provider is implemented in [`app/providers/search/semantic_scholar_provider.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/providers/search/semantic_scholar_provider.py). Note: class name `SemanticScholarProvider` was retained so no downstream consumers needed signature changes.
  - Abstracts returned by OpenAlex as inverted indices (`abstract_inverted_index`) are reconstructed into plain text via the internal `_reconstruct_abstract()` helper function.
  - Requests are identified using a polite pool `User-Agent` header and throttled via `_respect_rate_limit()` (minimum 1.0-second delay between calls).
- **Files Affected**:
  - [`app/providers/search/semantic_scholar_provider.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/providers/search/semantic_scholar_provider.py): Complete OpenAlex HTTP client implementation with inverted index reconstruction.
  - [`app/providers/search/tavily_provider.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/providers/search/tavily_provider.py): General web search provider interface.
  - [`app/pipeline/evidence_general.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/evidence_general.py): `_gather_sources()` function concurrently executes Tavily web search and OpenAlex academic search via `ThreadPoolExecutor(max_workers=2)`.
  - [`app/providers/api_provider.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/providers/api_provider.py): Fallback handling for `use_grounding=True` requests.
  - [`config/settings.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/config/settings.py): `search_provider` (default `"tavily"`), `enable_academic_search` (default `True`), `academic_max_results` (default `3`).

---

### 2. Batched Claim Extraction (`claim_extract.v4`)
- **What Changed**: Upgraded claim extraction from single-slide per LLM call to multi-slide batch processing using prompt template `claim_extract.v4.jinja`.
- **Why**: Multi-slide presentations previously generated dozens of sequential LLM calls for claim extraction alone, hitting Gemini's strict Requests Per Minute (RPM) ceiling and consuming excessive API overhead.
- **Key Details**:
  - **Prompt Template (`claim_extract.v4.jinja`)**: Renders multiple slides in a single prompt call. Each slide is wrapped in security boundary tags `<<<PRESENTATION_CONTENT_START>>>` and `<<<PRESENTATION_CONTENT_END>>>` labeled by slide header (e.g. `### Slide 3`). Output schema enforces mandatory `slide_number` attribution per extracted claim while preserving all 7 claim taxonomy categories (`performance`, `dataset`, `architecture`, `technology`, `algorithm`, `capability`, `business`) and disambiguation rules. Template `claim_extract.v3.jinja` remains untouched for instant rollback.
  - **Configuration (`claim_extraction_batch_size`)**: Added `claim_extraction_batch_size: int = 4` to [`config/settings.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/config/settings.py), allowing runtime throughput tuning.
  - **`RawClaimOutput` Model Update**: Extended `RawClaimOutput` schema in [`app/pipeline/claim_extraction.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/claim_extraction.py) with mandatory `slide_number: int`.
  - **Chunking Helper (`_chunk()`)**: Implemented `_chunk(items: list[T], size: int) -> list[list[T]]` to split valid non-empty slides into configured batch sizes.
  - **Call Flow & Telemetry**: `extract_claims()` iterates over slide chunks, calling `provider.complete()` with response schema `list[RawClaimOutput]` and recording telemetry under label `claim_extract.v4`.
  - **Failure Handling**: Catches `DailyQuotaExceeded` and immediately re-raises to propagate HTTP 429. For non-quota batch errors, logs warning with failed slide numbers, records `failed_slides.extend(batch_numbers)`, and continues processing remaining batches to ensure partial analysis reports can still be delivered.
- **Files Affected**:
  - [`app/prompts/templates/claim_extract.v4.jinja`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/prompts/templates/claim_extract.v4.jinja): New batched extraction prompt.
  - [`app/pipeline/claim_extraction.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/claim_extraction.py): `_chunk()` batching helper, updated `RawClaimOutput`, v4 rendering, `failed_slides` tracking.
  - [`config/settings.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/config/settings.py): Setting `claim_extraction_batch_size = 4`.

---

### 3. Gemini Free-Tier Quota & Error Handling Improvements
- **What Changed**: Standardized free-tier rate limit detection and structured error responses for Gemini API quota exhaustion.
- **Why**: Gemini free-tier imposes a strict cap of 500 requests per day per project per model (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`). Unhandled quota errors previously resulted in uninformative 500 Internal Server Errors or silent pipeline failures.
- **Key Details**:
  - **Structured Error Response**: Defined `DailyQuotaExceeded` exception class in [`app/errors.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/errors.py) with `code = "DAILY_QUOTA_EXCEEDED"` and `status = 429`.
  - **Error Payload**:
    ```json
    {
      "status": "error",
      "error": {
        "code": "DAILY_QUOTA_EXCEEDED",
        "message": "Gemini free-tier daily/rate quota exceeded. Try again later or switch to a paid tier."
      }
    }
    ```
  - **Provider Catching**: In [`app/providers/api_provider.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/providers/api_provider.py), `genai_errors.ClientError` with HTTP code 429 or string `"RESOURCE_EXHAUSTED"` is caught. If short retry delay parsed from error details is within ceiling (`_RPM_RETRY_DELAY_CAP_SECONDS`), it sleeps and retries once; otherwise, it raises `DailyQuotaExceeded`.
  - **Pipeline Propagation**: Pipeline modules (`claim_extraction.py`, `evidence_general.py`, `plausibility.py`, `run.py`) explicitly catch and re-raise `DailyQuotaExceeded` without swallowing or converting it into a 500 error.
- **Files Affected**:
  - [`app/errors.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/errors.py): `DailyQuotaExceeded` class definition.
  - [`app/providers/api_provider.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/providers/api_provider.py): 429 / `RESOURCE_EXHAUSTED` handling and `DailyQuotaExceeded` raising.
  - [`app/pipeline/claim_extraction.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/claim_extraction.py), [`app/pipeline/evidence_general.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/evidence_general.py), [`app/pipeline/plausibility.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/plausibility.py), [`app/pipeline/run.py`](file:///c:/Users/youss/Desktop/presentation-ai/presentation-ai/app/pipeline/run.py): Clean quota exception passthrough.
