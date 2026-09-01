# Full-stack integration contract

This document describes the supported contract between the full-stack backend and the AI service after the split extraction + ranking flow was merged into one endpoint.

## Endpoint

POST /api/v1/cv/evaluate

## Auth

- Requires the same service-to-service secret as the previous data endpoints.
- Header: `X-API-Key`
- Same fail-open behavior when `AI_SERVICE_API_KEY` is unset in local development.
- Same rate limit as the old extraction endpoint: `10 per hour`.

## Request

`multipart/form-data`

Fields:

- `file`: uploaded CV file, required
  - supported extensions: `.pdf`, `.docx`
  - validated by extension + magic-byte content check
  - max size: 10 MB
- `job_description`: required form field containing a JSON string
  - example: `{"title":"Data Analyst","required_skills":["Python","SQL"],"nice_to_have_skills":["Tableau"],"min_experience_years":3}`
  - parsed by `json.loads()` and then validated against `JobDescription`

Example request (curl):

```bash
curl -X POST "http://localhost:5000/api/v1/cv/evaluate" \
  -H "X-API-Key: $AI_SERVICE_API_KEY" \
  -F "file=@candidate.pdf" \
  -F 'job_description={"title":"Data Analyst","required_skills":["Python","SQL"],"nice_to_have_skills":["Tableau"],"min_experience_years":3}'
```

## Success response

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

If `RANKING_ENABLED` is `False`, the endpoint still returns the extracted CV but sets:

```json
{
  "success": true,
  "cv": { ... },
  "ranking": null
}
```

This is still HTTP `200`.

## Error responses

The endpoint reuses the existing error shape used elsewhere in the service:

```json
{ "success": false, "error": "..." }
```

### 400 Bad Request

- missing `file` field
- empty filename
- unsupported extension
- invalid file content signature
- missing `job_description` field
- malformed JSON in `job_description`
- `job_description` is not a JSON object

### 422 Unprocessable Entity

- `job_description` fails `JobDescription` validation
- extracted text is empty / no extractable text found in the file

### 401 Unauthorized

- invalid or missing `X-API-Key` when a key is configured

### 429 Too Many Requests

- rate limit exceeded (`10 per hour`)

### 502 Bad Gateway

- extraction fails across the entire model fallback chain (`ModelInferenceError`)

### 500 Internal Server Error

- unexpected server-side exception during extraction or ranking

## Important behavior

- This route does not redesign the underlying schema; it composes the existing `CVSchema`, `JobDescription`, and `RankingResult` models without changing field names or types.
- PII redaction is still performed in `clean_and_query()` exactly as before.
- Ranking is not attempted if extraction fails, because there is no valid CV to score.
- The old split endpoints were removed as part of this contract change; the supported API is the merged route.
