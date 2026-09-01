# AI Service — Integration Guide for the Full-Stack Team

This document is for the full-stack team. It covers the supported API contract between the
full-stack app and the AI service after the split extraction + ranking flow was merged into a
single request.

The service does not persist results; it returns the output directly in the HTTP response.

---

## 1. Quick overview

- Framework: Flask
- Supported data endpoint: one merged evaluation route
- Health endpoint: one liveness check
- Default local base URL: `http://localhost:5000`
- Every response returns JSON

The supported flow is now:

1. Upload a CV file and a job description to `POST /api/v1/cv/evaluate`
2. Receive both the extracted CV payload and the ranking result in one response
3. Display or store the result in your app

The old separate `POST /api/v1/cv/extract` and `POST /api/v1/rank` endpoints are no longer
part of the supported contract.

---

## 2. Authentication

Every data endpoint except `/api/v1/health` requires a static API key.

Header:
```http
X-API-Key: <value sent separately>
```

- Missing or wrong key → `401 Unauthorized`
- If `AI_SERVICE_API_KEY` is unset in local dev, the service may allow the request without
  auth. Do not rely on that in any shared or production environment.

---

## 3. Supported endpoints

### 3.1 `GET /api/v1/health`

Simple liveness check.

Request: no body.

Response:
```json
{ "status": "ok" }
```

---

### 3.2 `POST /api/v1/cv/evaluate`

Performs CV extraction and ranking in one multipart call.

Rate limit: `10 requests/hour per IP`.

Request:
- `Content-Type: multipart/form-data`
- Header: `X-API-Key: <...>`
- Required field: `file`
- Required field: `job_description`

`job_description` must be a JSON string in the form field, for example:
```json
{"title":"Data Analyst","required_skills":["Python","SQL"],"nice_to_have_skills":["Tableau"],"min_experience_years":3}
```

Example request (curl):
```bash
curl -X POST "http://localhost:5000/api/v1/cv/evaluate" \
  -H "X-API-Key: $AI_SERVICE_API_KEY" \
  -F "file=@candidate.pdf" \
  -F 'job_description={"title":"Data Analyst","required_skills":["Python","SQL"],"nice_to_have_skills":["Tableau"],"min_experience_years":3}'
```

The uploaded file must be a PDF or DOCX file, max 10 MB, with extension + magic-byte validation.
The `job_description` value is parsed with `json.loads()` and then validated against the
service schema.

Success response:
```json
{
  "success": true,
  "cv": {
    "personal_info": {
      "name": null,
      "email": null,
      "phone": null,
      "location": null,
      "linkedin": null,
      "github": null
    },
    "education": [],
    "experience": [],
    "projects": [],
    "skills": [],
    "inferred_skills": [],
    "certifications": [],
    "languages": []
  },
  "ranking": {
    "score": 83.4,
    "matched_skills": ["Python", "SQL"],
    "missing_skills": ["Power BI"],
    "semantic_fit": 0.8123,
    "breakdown": {
      "required_skills_total": 3,
      "required_skills_matched": 2,
      "required_match_ratio": 0.6667,
      "nice_to_have_skills_total": 1,
      "nice_to_have_skills_matched": 0,
      "nice_to_have_match_ratio": 0.0,
      "hard_skill_score": 0.5333,
      "hard_skill_weight": 0.7,
      "semantic_fit_raw": 0.8123,
      "semantic_fit_clamped": 0.8123,
      "semantic_weight": 0.3
    }
  }
}
```

If `RANKING_ENABLED` is `False`, the endpoint still returns the extracted CV and sets:
```json
{
  "success": true,
  "cv": { "...": "..." },
  "ranking": null
}
```

This remains an HTTP `200` response.

Error responses:

```json
{ "success": false, "error": "..." }
```

- `400`: missing `file`, empty filename, unsupported extension, invalid content signature,
  missing `job_description`, malformed JSON in `job_description`, or non-object JSON value
- `401`: missing or invalid `X-API-Key`
- `422`: `job_description` fails validation or extracted text is empty / not found
- `429`: rate limit exceeded
- `502`: extraction failed across the model fallback chain
- `500`: unexpected server-side exception during extraction or ranking

---

## 4. Notes for the full-stack integration

- The route does not redesign the underlying schemas; it composes the existing CV and ranking
  models without changing field names or types.
- PII redaction is still performed inside the extraction pipeline as before.
- Ranking is skipped if extraction fails, because there is no valid CV to score.
- The old split endpoints were removed as part of this contract update; the supported API is the
  merged route above.

---

## 5. Local setup

```bash
cd ai-service
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -e ".[dev,ui]"

pytest
# expected: project test suite passes

python -m app.main
# runs on http://localhost:5000 (or the port in FLASK_PORT)
```

Health check:
```bash
curl http://localhost:5000/api/v1/health
# expected: {"status": "ok"}
```

Streamlit UI:
```bash
cd ai-service
.venv\Scripts\activate
streamlit run ui/streamlit_app.py
```

This opens at `http://localhost:8501` and sends the merged single-call request using the same
HTTP contract as the backend.

---

## 6. `.env` template

```bash
# Hugging Face — CV extraction
HF_API_TOKEN=<sent separately>
HF_MODEL_ID_1=Qwen/Qwen2.5-3B-Instruct
HF_PROVIDER_1=featherless-ai
HF_MODEL_ID_2=mistralai/Mistral-7B-Instruct-v0.2
HF_PROVIDER_2=featherless-ai

# Embeddings — Gemini
EMBEDDING_PROVIDER=api
GEMINI_API_KEY=<sent separately>
EMBEDDING_API_MODEL=gemini-embedding-001
EMBEDDING_API_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/

# Service-to-service auth
AI_SERVICE_API_KEY=<sent separately>

# Flask
FLASK_DEBUG=True
FLASK_PORT=5000

# Feature flags
RANKING_ENABLED=True
```

Never commit this file to git.

---

## 7. Important caveats

- There is no persistence layer in the service.
- Ranking is still a best-effort signal; there is no evidence trail tying a matched skill back
to a specific CV segment yet.
- The rate limiter is in-memory and resets on restart.
- Extraction accuracy is still being improved and should be evaluated before production use in
  hiring-critical workflows.

Any ambiguity on the supported contract should be clarified with the service owner before
building against it.