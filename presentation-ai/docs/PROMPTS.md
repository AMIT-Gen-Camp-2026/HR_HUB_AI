# Prompt versions

Prompts live in `app/prompts/templates/*.v{N}.jinja` and are loaded by
`app/prompts/registry.py`. Never edit a shipped template in place — bump the version
and log the change below, so `eval/` can compare old vs new on the same labeled set.

| Template | Version | Date | Notes |
|---|---|---|---|
| claim_extract | v1 | initial | Batched per-slide. Tags every claim with `track`. |
| claim_extract | v2 | 2026-09-01 | Added explicit `<<<PRESENTATION_CONTENT_START>>>` / `<<<PRESENTATION_CONTENT_END>>>` injection defense boundaries. Removed `slide_number` from requested model output. |
| claim_extract | v3 | 2026-09-01 | Added comprehensive claim_type disambiguation guidance and concrete examples for all 7 categories (clarified technology vs capability, performance vs capability, architecture vs dataset, and technology vs algorithm). |
| fact_check | v1 | initial | Track "objective" only. Requires grounding tool. |
| plausibility_judgment | v1 | initial | Track "project_specific" only. Must return `reason`. |
| plausibility_judgment | v2 | 2026-09-01 | Added batched plausibility evaluation support for up to 3-5 claims per call with keyed `claim_id` outputs and individual fallback. |
| correction_generate | v1 | initial | Track "objective" + status=contradicted only. Evidence-only, no invention. |

## Guidelines for new prompt versions

- One behavioral change per version bump — makes eval diffs interpretable.
- Never remove the explicit "if you don't know, say unclear / don't invent" instruction
  from fact_check or correction_generate — this is a safety property, not a style choice.
- Run `eval/runners/run_extraction.py` against both versions before shipping a change.
