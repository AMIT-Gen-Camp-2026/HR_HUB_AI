# Changes Since Last Integration Handoff

Date: 2026-09-03

If you've already built against the earlier version of `docs/FULLSTACK_INTEGRATION.md`, here's exactly what changed and what you may need to update.

## Breaking / behavioral changes

- The authoritative score formula changed from the older hard-skill + semantic mix to the current required-coverage formula with a bounded preferred-skill bonus. The old `0.7 hard + 0.3 semantic` interpretation is no longer the contract.
- `score` is now based on required-skill coverage first, with preferred evidence capped and only applied to the uncovered required portion. A complete required match still yields `100.0`, but a preferred-only result is capped at `20.0`.
- `EMPTY` extraction status is now a first-class API state: it returns HTTP `200` with `ranking: null` instead of a numeric score. Clients must not treat `EMPTY` as a legitimate zero-score candidate.
- The current route is `POST /api/v1/cv/evaluate`; there is no supported older split `extract` + `rank` flow as part of the current contract.
- The response envelope now explicitly includes `extraction_status` and `extraction_metadata`, and these fields are part of the current supported contract.

## New fields (additive, safe to ignore if unused)

- `extraction_status`: string — current values are `SUCCESS`, `EMPTY`, and `FAILED`.
- `extraction_metadata`: object — provider/extraction trace metadata returned with the successful response.
- `model_used`: string | null — which model succeeded in the fallback chain.
- `provider`: string | null — provider name used by the successful model call.
- `attempt_number`: integer | null — attempt index in the fallback sequence.
- `fallback_occurred`: boolean — whether the successful model attempt came after an earlier failure.
- `cache_hit`: boolean — whether the extraction result was served from the in-memory validated snapshot cache.
- `taxonomy_recovered_skills`: list[str] — skills recovered by exact taxonomy matching that were not already present in the model output.
- `matched_required_skills`: list[str] — required-skill matches only.
- `missing_required_skills`: list[str] — required-skill misses only.
- `matched_preferred_skills`: list[str] — preferred-skill matches only.
- `missing_preferred_skills`: list[str] — preferred-skill misses only.
- `scoring_version`: string — currently `deterministic-hard-skills-v2`.
- `taxonomy_version`: string — currently `2026.09`.

## New failure/edge case to handle

- `EMPTY` extraction status is a valid non-error result. The exact response shape is:

```json
{
  "success": true,
  "cv": { "...": "..." },
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

Clients should show a “not enough CV data to score” or equivalent state rather than a `0% match` or a numeric zero-score interpretation.

## Input-quality guidance (no contract change, but worth knowing)

- The JD input path is still flat and string-based. If a user pastes a real JD verbatim, lines like section headings or sentence fragments can become literal required skill entries and lower the achievable score for every candidate.
- Examples of what not to paste as raw skill names include headings like `AI Image Generation` and sentence fragments like `Excellent presentation and communication skills.`. Those are not canonical skill names and they silently poison the match denominator.
- The fuller explanation and product guidance are in `docs/FULLSTACK_INTEGRATION.md` under the Job-description input hygiene section.

## Nothing changed here

- Auth remains `X-API-Key` and the route remains behind the same service-to-service key pattern used today.
- The base API shape stays `multipart/form-data` with a CV file plus a JSON-string `job_description` field.
- Rate limiting remains the same mechanism: Flask-Limiter with the current app-wide and route-specific caps.
- The model pipeline still uses a multi-attempt Hugging Face fallback chain; the difference is that extraction-status and metadata are now explicit contract fields, not hidden implementation details.
