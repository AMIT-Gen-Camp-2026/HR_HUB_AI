# AI Service — Integration Guide for the Full-Stack Team

This document is for the full-stack team. It covers everything needed to integrate with
the AI service: how many endpoints exist, the exact request/output shape for each one, and
how to get the project running after cloning it from GitHub — API and Streamlit UI both.

Last updated: 2026-08-29. For the full architecture (how everything works internally) see
`docs/ARCHITECTURE.md`; for the history of engineering decisions, `docs/DECISIONS.md`.

---

## 1. Quick overview

- **Framework:** Flask (not FastAPI).
- **Number of endpoints:** 3 — one health check, one CV extraction, one candidate-to-JD
  ranking.
- **Default local base URL:** `http://localhost:5000`
- **Every endpoint returns JSON.** Nothing else.
- **The service persists nothing.** Every output is a draft returned directly in the
  response — there's no database here. If you need to store results, that's on the
  full-stack backend.

---

## 2. Authentication — required before anything else works

Every endpoint except `/api/v1/health` is protected by a static API key.

**Every request must include this header:**

```
X-API-Key: <the value we'll send you separately>
```

- Missing or wrong header → `401 Unauthorized`
- If the key isn't configured on our side at all (local-dev-only situation), the endpoint
  runs with no auth enforced. **This must never be the case in any environment reachable by
  you or in production.**

The actual key value is sent through a separate, secure channel — not in this document.

---

## 3. Endpoints in detail

### 3.1 `GET /api/v1/health`

Simple liveness check. No auth required here (used by Docker healthcheck and monitoring).

**Request:** no body.

**Response — `200 OK`:**
```json
{ "status": "ok" }
```

---

### 3.2 `POST /api/v1/cv/extract`

Takes a CV file (PDF or DOCX) and returns its data as structured JSON.

**Rate limit:** 10 requests/hour per IP.

**Request:**
- `Content-Type: multipart/form-data`
- Header: `X-API-Key: <...>`
- A field named `file` — exactly one file, `.pdf` or `.docx` extension only.
- Max file size: **10 MB**.

Example (curl):
```bash
curl -X POST http://localhost:5000/api/v1/cv/extract \
  -H "X-API-Key: <your-key>" \
  -F "file=@candidate_cv.pdf"
```

**Response — `200 OK`** (success):
```json
{
  "success": true,
  "cv": {
    "personal_info": {
      "name": "Ahmed Hassan",
      "email": "ahmed.hassan@example.com",
      "phone": "01012345678",
      "location": "Cairo, Egypt",
      "linkedin": "linkedin.com/in/ahmedhassan",
      "github": "github.com/ahmedhassan"
    },
    "education": [
      {
        "degree": "B.Sc. Computer Science",
        "institution": "Cairo University",
        "graduation_year": "2022"
      }
    ],
    "experience": [
      {
        "job_title": "Backend Engineer",
        "company": "Acme Corp",
        "start_date": "2022-06",
        "end_date": "Present"
      }
    ],
    "projects": [
      {
        "name": "Inventory API",
        "description": "REST API for warehouse stock tracking",
        "technologies_mentioned": ["Django", "PostgreSQL", "Redis"]
      }
    ],
    "skills": ["Python", "Django", "PostgreSQL", "Docker"],
    "inferred_skills": ["REST API design", "Database schema design"],
    "certifications": ["AWS Certified Developer – Associate"],
    "languages": ["Arabic", "English"]
  }
}
```

**Every field is optional and may come back empty** (`null` or `[]`) if the model didn't
find that information in the CV. **`email` and `phone` specifically are guaranteed to be
accurate** — they're extracted directly from the text via regex, not from the model, so if
they're present in the CV they'll always come back correct.

**Failure responses:**

| Status | Cause | Body shape |
|---|---|---|
| `400` | No `file` in the form-data, disallowed extension, or file content doesn't match its extension (magic-byte check) | `{"success": false, "error": "<descriptive message>"}` |
| `401` | Missing or wrong `X-API-Key` | `{"success": false, "error": "Missing or invalid API key."}` |
| `422` | File was read but no extractable text was found (e.g. a scanned image with no OCR) | `{"success": false, "error": "No extractable text found in file."}` |
| `429` | Rate limit exceeded (10/hour) | (Flask-Limiter's default message) |
| `502` | Every model in the fallback chain failed to return valid JSON | `{"success": false, "error": "Model inference failed. Please try again."}` |
| `500` | Unexpected internal error | `{"success": false, "error": "Internal server error."}` |

**Timing note:** a single CV extraction makes a real LLM call — expect **3 to 15 seconds**
depending on load on the Hugging Face side. Design your UI/UX around this not being
instant (a clear loading state, not a short timeout).

---

### 3.3 `POST /api/v1/rank`

Takes a CV (usually the same JSON returned by `/cv/extract`, as-is) plus a Job Description,
and returns a match score. **This is fully deterministic — no LLM call happens here, just
one embedding API call (usually under a second).**

**Rate limit:** 60 requests/hour per IP.

**Request:**
- `Content-Type: application/json`
- Header: `X-API-Key: <...>`

```json
{
  "candidate": {
    "skills": ["Python", "Django", "PostgreSQL"],
    "inferred_skills": ["REST API design"],
    "experience": [
      { "job_title": "Backend Engineer", "company": "Acme Corp" }
    ],
    "projects": []
  },
  "job_description": {
    "title": "Backend Engineer",
    "required_skills": ["Python", "Django", "PostgreSQL", "Docker"],
    "nice_to_have_skills": ["Kubernetes", "AWS"],
    "min_experience_years": 2
  }
}
```

**Notes on the input shape:**
- `candidate` is the same shape as the `cv` object returned by `/cv/extract` — you can pass
  it through as-is (`personal_info` isn't even needed here, scoring doesn't use it).
- `job_description.title` is **required**. Everything else is optional.
- `min_experience_years` is currently accepted but **not used** in the score — `Experience`
  doesn't have structured enough start/end dates to compute years from. This is a known,
  documented gap in `docs/ARCHITECTURE.md`.
- **Any field not in the schema will reject the whole request** (`422`) — the schemas are
  strict (`extra="forbid"`) specifically to catch a mismatch between your side and ours
  early.

**Response — `200 OK`:**
```json
{
  "success": true,
  "result": {
    "score": 82.5,
    "matched_skills": ["Python", "Django", "PostgreSQL"],
    "missing_skills": ["Docker"],
    "semantic_fit": 0.74,
    "breakdown": {
      "required_skills_total": 4,
      "required_skills_matched": 3,
      "required_match_ratio": 0.75,
      "nice_to_have_skills_total": 2,
      "nice_to_have_skills_matched": 0,
      "nice_to_have_match_ratio": 0.0,
      "nice_to_have_matched_skills": [],
      "nice_to_have_missing_skills": ["Kubernetes", "AWS"],
      "hard_skill_score": 0.6,
      "hard_skill_weight": 0.7,
      "semantic_fit_raw": 0.74,
      "semantic_fit_clamped": 0.74,
      "semantic_weight": 0.3
    }
  }
}
```

- `score`: 0 to 100. Formula: `70% × hard_skill_score + 30% × semantic_fit`.
- `matched_skills`/`missing_skills` represent `required_skills` only (not the nice-to-have
  ones — those live inside `breakdown`).
- **There is no evidence/context for any skill yet** — you won't know exactly where in the
  CV a skill was mentioned, just that it matched. This is a known gap, planned.

**Special case — ranking disabled:**
```json
{ "success": false, "error": "Ranking is switched off." }
```
This comes back as `200 OK` (not an error status) if the `RANKING_ENABLED` feature flag is
off on our side. Treat it as "feature currently unavailable", not an actual error.

**Failure responses:**

| Status | Cause |
|---|---|
| `400` | Body isn't valid JSON |
| `401` | Missing or wrong `X-API-Key` |
| `422` | `candidate` or `job_description` doesn't match the schema (e.g. missing `title`, or an unknown extra field) — the body includes Pydantic's detailed error list |
| `429` | Rate limit exceeded (60/hour) |
| `500` | Unexpected internal error |

---

## 4. Running the project from scratch (after cloning from GitHub)

### Requirements
- Python **3.11 or newer** (actually tested on 3.12).
- A `.env` file (we'll send you the real values separately — template in section 5).

### Steps

```bash
git clone <repo-url>
cd ai-service

# 1) Put a .env file (template in section 5 below) in this same folder (ai-service/)

# 2) Virtual environment
python -m venv .venv

# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 3) Install the project + dependencies (dev = for tests, ui = for Streamlit)
pip install -e ".[dev,ui]"

# 4) Confirm everything is logically sound (no real network call in these)
pytest
# Expected: 22 passed

# 5) Confirm the embeddings API (Gemini) actually works with the real key
python -m scripts.check_embeddings
# Expected: [PASS] on the last line

# 6) Run the API itself
python -m app.main
# Runs on http://localhost:5000 (or whatever port is in FLASK_PORT in .env)
```

**Quick check the API is up:**
```bash
curl http://localhost:5000/api/v1/health
# Expected: {"status": "ok"}
```

### Running the Streamlit UI (a manual-testing tool, not part of the integration itself)

In a second terminal (with the API still running in the first):
```bash
cd ai-service
.venv\Scripts\activate      # or source .venv/bin/activate on macOS/Linux
streamlit run ui/streamlit_app.py
```
Opens on `http://localhost:8501` automatically. Useful for uploading a test CV and seeing
the output shape with your own eyes before writing integration code.

### Running with Docker (alternative to the manual steps)
```bash
docker compose up --build
# ai-service on :5000, ui on :8501
```

---

## 5. `.env` file template (real values sent separately)

Copy this into a file named `.env` inside `ai-service/`, and replace the values with the
real keys we'll send you:

```bash
# ============================================================
# Hugging Face — CV extraction
# ============================================================
HF_API_TOKEN=<sent separately>

HF_MODEL_ID_1=Qwen/Qwen2.5-3B-Instruct
HF_PROVIDER_1=featherless-ai
HF_MODEL_ID_2=mistralai/Mistral-7B-Instruct-v0.2
HF_PROVIDER_2=featherless-ai

# ============================================================
# Embeddings — Gemini (the default)
# ============================================================
EMBEDDING_PROVIDER=api
GEMINI_API_KEY=<sent separately>
EMBEDDING_API_MODEL=gemini-embedding-001
EMBEDDING_API_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/

# ============================================================
# Service-to-service auth — must match the value you send as X-API-Key
# ============================================================
AI_SERVICE_API_KEY=<sent separately>

# ============================================================
# Flask
# ============================================================
FLASK_DEBUG=True
FLASK_PORT=5000

# ============================================================
# Feature flags
# ============================================================
RANKING_ENABLED=True
```

**Never commit this file to git** — it should already be covered by `.gitignore` in the
repo.

---

## 6. Important things to know before building on top of this

- **No persistence.** Every response is returned once; nothing is stored on our side. If
  you need to keep a history of extraction/ranking results, that has to happen on your end.
- **No evidence trail for ranking yet.** `matched_skills` is just names, with no pointer to
  where in the CV that skill was mentioned.
- **Extraction accuracy hasn't been formally measured yet** — we're working on adding a
  real evaluation dataset next sprint. Fine for early use/demos, but if results are going to
  feed into an actual hiring decision, we need to measure this first.
- **The rate limiter is currently in-memory** — it resets on server restart and isn't
  shared across multiple workers. Fine for development/demo scale, not for a large-scale
  production deployment.

Any question or ambiguity on any endpoint — send it over and we'll clarify or update this
document.