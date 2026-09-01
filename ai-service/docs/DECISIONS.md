# Decision log

One short entry per decision. Date, decision, reason, alternative rejected.
Append; never rewrite history.

---

## 2026-08-19 — Four providers behind one adapter

**Decision.** The pipeline talks to a `ProviderAdapter`. Four implementations: `api`, `hf`,
`local`, `stub`. Selection is one environment variable.

**Reason.** The camp needs to run in three different situations — with a hosted key, with
open models, and offline on demo day — without three codebases. Building the adapter first
makes provider choice a configuration table rather than a rewrite.

**Rejected.** Hard-coding one provider and "porting later". Porting later never happens
before the deadline.

---

## 2026-08-19 — Stub is the development default

**Decision.** `PROVIDER=stub` in the test configuration and in local UI work.

**Reason.** A camper debugging a screen should not spend the budget. It also makes every
AI feature unit-testable with no network.

---

## 2026-08-19 — Skills carry evidence and a source

**Decision.** Every extracted skill records `source` (explicit | inferred) and the verbatim
`evidence` span it came from.

**Reason.** Without evidence the reviewer has to re-read the CV to trust the output, which
removes the time the feature was supposed to save. Without `source`, an inferred skill is
weighted the same as a declared one, which is wrong.

---

## 2026-08-19 — Invention guard in postprocess, not in the prompt alone

**Decision.** After the model returns, any skill whose name does not appear literally in the
document is dropped and a warning is recorded.

**Reason.** Prompt instructions reduce hallucination; they do not eliminate it. For inferred
skills, precision matters more than recall — a missing skill costs thirty seconds, an invented
one puts a false claim on a candidate's record.

---

## 2026-08-28 — Reality check: the four-decisions above never shipped

**Decision.** Stop describing the system as if `ProviderAdapter`/`stub`/`local` providers,
per-skill `source`+`evidence`, and the invention guard exist. They don't. The service that
actually runs today is: Flask (not FastAPI), a single extraction path through
`app/providers/hf_provider.py` (Hugging Face Inference Providers, with a `MODEL_CHAIN`
fallback list — no `api`/`local`/`stub` switch), and a `CVSchema` with no `source`/`evidence`
fields. `docs/ARCHITECTURE.md` and this README were written for a Sprint-2 design
(FastAPI + provider abstraction) that was scrapped because it was never actually wired up
at runtime — `config/settings.py` still has a comment documenting exactly that.

**Reason.** A decision log that describes a system nobody is running is worse than no log —
it actively misleads the next person (including a future instance of whoever's working on
this) into building on top of something that isn't there. Every entry above this one is kept
per the "never rewrite history" rule, but should be read as **historical intent, not current
state** starting today.

**What's actually true today** (see `docs/ARCHITECTURE.md`, rewritten same day):
- Flask app (`app/main.py`), two endpoints: `/api/v1/cv/extract`, `/api/v1/rank`.
- One extraction provider: `app/providers/hf_provider.py`, HF Inference Providers with a
  2-model fallback chain (`MODEL_CHAIN` in `config/settings.py`).
- Ranking is 100% deterministic (`app/pipeline/ranking.py`) — no LLM call in the scoring
  path. That part of the original philosophy ("a score is computed, not generated") did
  ship, and still holds.
- No `source`/`evidence`/invention-guard on skills. `matched_skills` in `RankingResult` is
  just names — flagged as a gap, not fixed yet.

---

## 2026-08-28 — Embeddings: OpenAI-compatible API (Gemini) as the default provider

**Decision.** `app/providers/embeddings.py` supports two providers behind
`EMBEDDING_PROVIDER`: `local` (sentence-transformers, `BAAI/bge-m3`) and `api` (any
OpenAI-compatible embeddings endpoint, called via raw `httpx`, not the `openai` SDK).
`api` + Gemini (`gemini-embedding-001`) is now the default in `.env.example`.

**Reason.** `local` needs `sentence-transformers` + `torch` (~GB-scale install, and the
old Sprint-2 FastAPI target this was built for never ran) — not something you want as the
default on a laptop mid-camp. Gemini's OpenAI-compatibility endpoint gives production-grade
embedding quality with a lightweight HTTP call, no local model weights.

**Bug found and fixed during this switch.** The `api` path was first implemented with the
`openai` SDK's client, which sorts returned embeddings by their `index` field automatically.
When it was rewritten as a raw `httpx.post()` call, that sort was dropped. If Gemini ever
returns a batch response out of input order, CV and JD embeddings get silently swapped —
`semantic_fit()` returns a confident-looking wrong number, no exception, no log. Fixed by
re-sorting `data["data"]` by `"index"` before returning. Covered by a mocked test that
deliberately reverses the response order (`/tmp` scratch test during review; a permanent
version should live in `tests/unit/test_embeddings.py` — not yet added).

Also fixed: `httpx.HTTPStatusError` was surfaced via `raise_for_status()` alone, which drops
the response body — so an invalid key or an invalid model name just showed up as
`401`/`400` with no message. Now the response body is included in the raised error.

**Rejected.** Keeping the `openai` SDK dependency just to talk to a non-OpenAI, OpenAI-compatible
endpoint. `httpx` direct is one dependency lighter and the response shape is simple enough
not to need a client wrapper — as long as the `index` sort isn't dropped again.

**Verification.** `scripts/check_embeddings.py` exists specifically to catch a provider that
returns *numbers* but the *wrong* numbers — it embeds two similar sentences and one unrelated
one and asserts cosine similarity is meaningfully higher for the similar pair. Passing this
is a necessary check before trusting `semantic_fit()` in production, run it after any change
to `EMBEDDING_PROVIDER`/`EMBEDDING_API_MODEL`/`EMBEDDING_API_BASE_URL`.

---

## 2026-08-28 — redact() gets wired into the real pipeline

**Decision.** `app/pipeline/redact.py` existed, was tested (`tests/unit/test_redaction.py`),
and was never called from `app/pipeline/run.py`. CV text — including email, phone, and
national ID — was being sent in full to a third-party model provider (HF Inference
Providers). `clean_and_query()` now calls `redact()` on the cleaned text before
`build_prompt()`, and `assert_clean()` on the final prompt as a safety net that refuses to
send the call if anything slipped through.

**Problem this created, and how it was resolved.** `CVSchema.personal_info` has `email` and
`phone` fields that are supposed to come *from the model reading the CV*. Redacting those
strings before the model ever sees them means the model can never fill them in — trading a
privacy bug for a correctness bug. Resolved by adding `extract_contact_info()` to
`redact.py`: a regex pass over the *pre-redaction* text that pulls email/phone directly
(deterministic pattern match — there was never a good reason to route these two fields
through an LLM in the first place). `run.py` uses this to fill
`personal_info.email`/`personal_info.phone` on the returned `CVSchema` directly, overriding
whatever the model returned for those two fields specifically.

**Scope, explicitly.** This redacts *identifier strings* (email, phone, 14-digit national
ID, any 10+ digit number) from what leaves the platform. It does **not** anonymize the CV —
the candidate's name, job titles, companies, and everything else still reaches the model
provider as-is, because there's no reliable regex for "is this a person's name" and this
project doesn't have NER. If full anonymization is ever a hard requirement (not just
identifier-stripping), that's a separate, bigger piece of work.

**Covered by** `tests/unit/test_redaction_integration.py` (new) — asserts the exact strings
sent to `query_model` never contain the raw email/phone/national ID, and that
`personal_info.email`/`phone` are still populated correctly (and can't be overridden by a
hallucinating model, since the local regex value wins).

---

## 2026-08-28 — Dockerfile/Makefile/docker-compose fixed to match the Flask app that exists

**Decision.** `Dockerfile` ran `uvicorn app.main:app` (ASGI server against a Flask/WSGI app —
this does not work), exposed port 8100 while `config/settings.py` defaults `FLASK_PORT` to
5000 and `ui/streamlit_app.py` hardcodes `http://127.0.0.1:5000`, and health-checked
`/health` when the real route is `/api/v1/health`. `Makefile`'s `run`/`test` targets had the
same `uvicorn`/`PROVIDER=stub` assumptions. None of this was runnable as written.

**Reason to fix now, not later.** These aren't stylistic — `docker compose up` would build
successfully and then crash on container start, which is a much worse debugging experience
than a docs mismatch. Standardized everything on port 5000 (matching what the Streamlit UI
already hardcodes) and on `gunicorn` for the containerized/production path (`make run` still
uses Flask's own dev server via `python -m app.main` for local work).

**Known follow-up, not fixed here.** `gunicorn --workers 2` means the in-memory rate limiter
(`Flask-Limiter`) and the embeddings `_CACHE` dict are **not shared across workers** — each
worker has its own copy, so the real rate limit is `N × configured limit` and cache hit rate
drops. Fine for now; needs a shared backend (Redis, most likely) before this goes past a
single-worker deployment.

---

## 2026-08-31 — Merged extraction and ranking into a single route

**Decision.** `POST /api/v1/cv/evaluate` replaced the old two-step flow (`/api/v1/cv/extract` + `/api/v1/rank`) with one multipart request carrying the CV file and a JSON-string `job_description` field. The route extracts the CV, validates it, then optionally ranks it in the same response; when `RANKING_ENABLED` is off, extraction still succeeds and the `ranking` field is `null` instead of failing the request.

**Reason.** A single round-trip is cheaper and simpler for the full-stack client: one file upload and one server round-trip instead of extract, then re-POST the result to rank. This reduces latency, avoids a redundant payload round-trip, and keeps the orchestration logic in the route layer only — the underlying extraction and scoring functions are untouched.

**Rejected / deferred.** We did not keep the old endpoints as backward-compatible aliases. The split contract was removed outright because the new merged route is the only supported API and the task explicitly required replacing the old route contract rather than maintaining two versions in parallel.

---

## 2026-08-29 — Minimal API key auth before integration, not after

**Decision.** Both data-touching endpoints (`/api/v1/cv/extract`, `/api/v1/rank`) now
require an `X-API-Key` header matching `AI_SERVICE_API_KEY` (`app/security/auth.py`).
`/api/v1/health` stays open — it's used by Docker's `HEALTHCHECK` and monitoring, which
shouldn't need to know about service auth. If `AI_SERVICE_API_KEY` is unset, the endpoints
fail-open (no auth enforced) and a single warning is logged — this keeps local dev and the
existing test suite working with zero changes, but means **this must be set before the
service is reachable by anything other than a developer's own machine**.

**Reason.** The decision to start the full-stack integration now, before the bigger gaps
(evaluation dataset, evidence trace, taxonomy coverage — see the "Known architectural gaps"
section of `docs/ARCHITECTURE.md`) are closed, was made deliberately: those gaps affect
*quality*, not *exposure*. Auth is different — without it, anything that can reach the
service can spend the Gemini/HF quota attached to it. That's a cost/abuse risk, not a
quality one, and costs nothing to close now versus later. This was the one item pulled out
of the "next sprint" list and done immediately instead.

**Deliberately not done here** (tracked for the next sprint, not blocking this
integration): per-client keys/scopes, key rotation, a shared rate-limit backend across
`gunicorn` workers (see the 2026-08-28 Dockerfile entry above), and a real
JWT/OAuth layer if the full stack ends up needing per-user permissions rather than one
shared service-to-service secret.

**Covered by** `tests/integration/test_auth.py` — key required/rejected/accepted, `/health`
always open, and the fail-open behavior when the key isn't configured.

---

## *(next entry)*