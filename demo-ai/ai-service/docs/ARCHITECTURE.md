# Architecture

## Why the AI service is a separate container

Three reasons. Every camper should be able to give all three.

1. **Its dependency tree is enormous and unrelated to the core API** — transformers, torch,
   audio libraries. Putting them in the same image triples build time for everyone.
2. **Its latency profile is incompatible.** A core API request is measured in milliseconds;
   a generation call is measured in seconds. Sharing a process means one slow generation ties
   up a worker that should be serving screens.
3. **Its failure must be survivable.** Every AI feature can be switched off with the product
   still fully usable. That guarantee is only credible if the AI code can literally stop
   running without taking anything else down.

## Request path

```
core API
   │  HTTP, internal network only
   ▼
/api/v1/cv/parse
   │
   ├─ feature flag check ──────► off? return a documented "disabled" response
   │
   ├─ extract_text      bytes → text, structure preserved
   ├─ normalize         Arabic forms, digits, whitespace
   ├─ redact            identifiers removed — REFUSES rather than sends
   ├─ prompts.render    versioned template
   ├─ provider.complete api | hf | local | stub
   ├─ schema validate   one repair attempt, then fail loudly
   ├─ postprocess       canonical ids, evidence check, invention guard
   └─ telemetry         model, prompt, latency, tokens, cost
   │
   ▼
draft result — never written to a record without a human action
```

## The provider boundary

Nothing outside `app/providers/` imports a provider SDK. Nothing inside `app/pipeline/`
knows which provider it is talking to. That is what makes the three scenarios a
configuration table rather than three codebases.

## What lives where

| Concern | Location | Rule |
|---|---|---|
| The output contract | `app/schemas/` | Change it and you have changed the API |
| Prompts | `app/prompts/templates/` | Versioned files, reviewed in PRs |
| Provider specifics | `app/providers/` | The only place an SDK may be imported |
| Business steps | `app/pipeline/` | Provider-agnostic |
| Skill vocabulary | `app/skills/taxonomy.yaml` | Grown from the job profile checklists |
| Numbers | `eval/` | A feature without a number is not accepted |
| Experiments | `notebooks/` | **Never imported by `app/`** |
