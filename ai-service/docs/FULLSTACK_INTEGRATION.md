# Full-stack integration contract

This document describes the current supported contract between the full-stack backend and the AI service. It reflects the code in `app/main.py`, `app/pipeline/ranking.py`, `app/pipeline/run.py`, `app/schemas/cv.py`, `app/security/auth.py`, and related provider files as they exist today.

## Endpoint

Supported route: `POST /api/v1/cv/evaluate`

This is the only active evaluation route. The older split `extract` + `rank` flow is not the current supported contract.

## Auth and rate limits

- Header: `X-API-Key`
- Required only when `AI_SERVICE_API_KEY` is configured.
- If `AI_SERVICE_API_KEY` is unset, the route intentionally fails open for local development and tests, and a warning is logged once.
- Flask-Limiter is configured at the app level with `30 per hour` and the evaluation route adds a stricter per-endpoint limit of `10 per hour`.
- `GET /api/v1/health` remains open and is not protected by the API key.

## Request

`multipart/form-data`

Fields:

- `file`: required CV upload
  - supported extensions: `.pdf`, `.docx`
  - validated by filename extension and magic-byte/content checks
  - stored temporarily in the upload directory, then deleted after processing
- `job_description`: required form field containing a JSON string
  - this is parsed with `json.loads()` and then validated into `JobDescription`
  - required shape today: `title`, `required_skills`, optional `nice_to_have_skills`, optional `min_experience_years`

Example request:

```bash
curl -X POST "http://localhost:5000/api/v1/cv/evaluate" \
  -H "X-API-Key: $AI_SERVICE_API_KEY" \
  -F "file=@candidate.pdf" \
  -F 'job_description={"title":"Data Analyst","required_skills":["Python","SQL"],"nice_to_have_skills":["Tableau"],"min_experience_years":3}'
```

`JobDescription` also accepts the legacy input alias `job_title` and the legacy `preferred_qualifications` field, but the canonical API fields are `title`, `required_skills`, and `nice_to_have_skills`.

## Response shape

The route returns a JSON envelope with `success`, `cv`, `ranking`, `extraction_status`, and `extraction_metadata`.

### Successful extraction with ranking

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
    "score": 66.67,
    "matched_skills": ["Python", "SQL"],
    "missing_skills": ["Power BI"],
    "matched_required_skills": ["Python", "SQL"],
    "missing_required_skills": ["Power BI"],
    "matched_preferred_skills": [],
    "missing_preferred_skills": ["Tableau"],
    "semantic_fit": 0.0,
    "breakdown": {
      "required_skills_total": 3,
      "required_skills_matched": 2,
      "required_match_ratio": 0.6667,
      "nice_to_have_skills_total": 1,
      "nice_to_have_skills_matched": 0,
      "nice_to_have_match_ratio": 0.0,
      "nice_to_have_matched_skills": [],
      "nice_to_have_missing_skills": ["Tableau"],
      "hard_skill_score": 0.6667,
      "hard_skill_weight": 1.0,
      "semantic_fit_raw": 0.0,
      "semantic_fit_clamped": 0.0,
      "semantic_weight": 0.0,
      "taxonomy_version": "2026.09",
      "scoring_version": "deterministic-hard-skills-v2"
    }
  },
  "extraction_status": "SUCCESS",
  "extraction_metadata": {
    "cache_hit": false,
    "model_used": "some-model",
    "provider": "hf-inference",
    "attempt_number": 1,
    "fallback_occurred": false,
    "taxonomy_recovered_skills": ["Prompt Engineering"]
  }
}
```

### Current ranking semantics

The authoritative score is no longer a 70/30 hard-skill + semantic mix. The current engine is strictly a required-coverage score with a bounded preferred bonus.

Current formula in `app/pipeline/ranking.py`:

```text
R = matched_required / unique_required, or None if there are no required skills
P = matched_preferred / unique_preferred, or None if there are no preferred skills

if R is not None:
    H = R + (0.2 * P * (1 - R))
else:
    H = 0.2 * P

score = round(min(H, 1.0) * 100, 2)
```

Interpretation:

- Required skills are the primary determinant of the score.
- Preferred skills add a bounded bonus only to the uncovered portion of required coverage.
- A fully matched required list always yields `100.0`.
- A preferred-only result is capped at `20.0` when no required skills exist.
- Duplicate JD entries are deduplicated before ratio calculation; duplicate candidate entries do not inflate the count.

Concrete examples:

- all required matched, no preferred: `100.0`
- partial required, all preferred matched: `100 * (R + 0.2 * P * (1 - R))`
- no required list, all preferred matched: `20.0`
- no matched evidence at all: `0.0`

`semantic_fit` appears in the ranking result and in `breakdown`, but it is non-authoritative under the current configuration because `SEMANTIC_WEIGHT = 0.0`. In other words, the value may be present, but it does not affect the final numeric `score` and must not be treated as a weighting factor for scoring decisions.

### Fields currently present in `ranking`

The current fields are:

- `score`: float, authoritative numeric score
- `matched_skills`: required-skill matches only
- `missing_skills`: required-skill misses only
- `matched_required_skills`: required-skill match list
- `missing_required_skills`: required-skill miss list
- `matched_preferred_skills`: preferred-skill match list
- `missing_preferred_skills`: preferred-skill miss list
- `semantic_fit`: diagnostic value, currently non-authoritative and usually `0.0`
- `breakdown`: dictionary with the actual keys currently emitted by `ranking.py`

Breakdown keys currently include:

- `required_skills_total`
- `required_skills_matched`
- `required_match_ratio`
- `nice_to_have_skills_total`
- `nice_to_have_skills_matched`
- `nice_to_have_match_ratio`
- `nice_to_have_matched_skills`
- `nice_to_have_missing_skills`
- `hard_skill_score`
- `hard_skill_weight`
- `semantic_fit_raw`
- `semantic_fit_clamped`
- `semantic_weight`
- `taxonomy_version`
- `scoring_version`

`scoring_version` is currently `deterministic-hard-skills-v2` and `taxonomy_version` is currently `2026.09`.

### Ranking disabled

If `RANKING_ENABLED` is `False`, the endpoint still returns the extracted CV but sets:

```json
{
  "success": true,
  "cv": { "...": "..." },
  "ranking": null,
  "extraction_status": "SUCCESS",
  "extraction_metadata": { "...": "..." }
}
```

This remains HTTP `200` and must not be treated as a legitimate numeric zero-score result.

## Extraction status

The current extraction-status values are:

- `SUCCESS`: the extracted CV contains evidence such as skills, inferred skills, experience, projects, education, certifications, languages, or a non-empty name.
- `EMPTY`: the validated CV is structurally present but has no evidence fields populated.
- `FAILED`: the model chain failed and the route returned `502` rather than ranking.

Important behavior: `EMPTY` is returned as `ranking: null` and an HTTP `200`. It is not the same as a valid zero-score candidate. A valid non-empty CV with no matching skills can still receive `0.0` as a score; `EMPTY` means “nothing worth ranking was extracted yet.”

Example `EMPTY` response:

```json
{
  "success": true,
  "cv": {
    "personal_info": { "name": null, "email": null, "phone": null, "location": null, "linkedin": null, "github": null },
    "education": [],
    "experience": [],
    "projects": [],
    "skills": [],
    "inferred_skills": [],
    "certifications": [],
    "languages": []
  },
  "ranking": null,
  "extraction_status": "EMPTY",
  "extraction_metadata": {
    "cache_hit": false,
    "model_used": "some-model",
    "provider": "hf-inference",
    "attempt_number": 1,
    "fallback_occurred": false,
    "taxonomy_recovered_skills": []
  }
}
```

## Extraction metadata

The route exposes a nested `extraction_metadata` object when extraction has run. Current fields include:

- `model_used`: model name returned by the successful attempt
- `provider`: provider used by that model attempt
- `attempt_number`: attempt index in the model chain, starting at 1
- `fallback_occurred`: boolean indicating whether the success came after a failed earlier attempt
- `cache_hit`: boolean indicating whether a valid in-memory snapshot was reused
- `taxonomy_recovered_skills`: list of taxonomy items recovered by exact taxonomy-text matching that were not already present in the model output

This metadata is additive; clients may ignore it if they do not need provider-level traceability.

## Taxonomy recovery

`taxonomy_recovered_skills` is not a separate scoring dimension; it is an explanation field. It records skills the service explicitly found in the source text via taxonomy-term scanning (exact names/aliases), even when the model's extracted `skills` or `inferred_skills` array did not include them. This is meant to make the extraction output auditable and to avoid losing literal skill terms that are present in the document but omitted by the model.

## Job-description input hygiene

This is a practical warning for the UI layer that builds the `job_description` payload.

The ranker accepts a flat list of strings. It does not classify headings, sentences, or narrative text as “not skills.” If a JD is pasted verbatim from a document, non-skill lines such as section headers like `AI Image Generation` or sentences like `Excellent presentation and communication skills.` become literal `required_skills` or `nice_to_have_skills` entries. Those entries are treated as unmatchable skill strings unless they happen to correspond exactly to a real taxonomy entry or candidate text, and they silently reduce the best achievable score for every candidate.

This is a product/input-quality problem, not a scoring bug. The safe design is to warn or sanitize pasted JD text before sending it, especially for headings, bullet labels, and full-sentence fragments.

## Error responses

The endpoint uses this payload style for failures:

```json
{ "success": false, "error": "..." }
```

Current HTTP patterns in the route:

- `400 Bad Request`: missing file, missing `job_description`, invalid JSON, unsupported extension, bad file signature, empty filename
- `401 Unauthorized`: invalid or missing `X-API-Key` when configured
- `422 Unprocessable Entity`: invalid `JobDescription` payload or no extractable text in the file
- `429 Too Many Requests`: rate limit exceeded
- `502 Bad Gateway`: model chain failed across all configured candidates (`ModelInferenceError`)
- `500 Internal Server Error`: unexpected server-side exception during extraction or ranking

## Important behavior

- The route does not redesign the underlying schema; it uses the existing `CVSchema`, `JobDescription`, and `RankingResult` models.
- PII redaction still happens before the model call; the extracted email and phone are restored from pre-redaction regex extraction and written back to `personal_info` on the returned CV.
- Ranking is only attempted when a valid CV exists and `extraction_status` is not `FAILED`.
- The final numeric score is a deterministic ranking result, not an LLM-generated value.
- `semantic_fit` is still returned for diagnostics, but it is not an authoritative score input under the current policy.
