## What changed

<!-- One or two sentences. -->

## Which scenario did you test against?

- [ ] `stub`
- [ ] `api`
- [ ] `hf`
- [ ] `local`

## Checklist

- [ ] Output is validated against a Pydantic schema — no prose parsing
- [ ] Prompt changes bumped the template version
- [ ] Telemetry still records model version, prompt version, latency and tokens
- [ ] The feature still works with its kill switch off
- [ ] No secret, no real CV, no personal identifier added to the repository
- [ ] Tests pass with `PROVIDER=stub`
- [ ] If this changes extraction behaviour: the evaluation was re-run and the number is in the PR

## Metric before / after

<!-- Required if this touches extraction, ranking or the assistant. -->
