# AMIT Instructor Hub — AI Service

CV parsing, skill extraction, candidate ranking, demo-video assessment and the internal
assistant. Runs as its own container so that its dependencies, its latency profile and its
failures stay isolated from the core API.

**Owner:** AI Track · AMIT Gen Camp 2026
**Companion documents:** `docs/ARCHITECTURE.md` · SRS — AMIT Instructor Hub v2.0 · AI Track Engineering Playbook

---

## The one rule

> A language model is used where **language** is the output.
> Anything that produces a **score, a decision, a schedule or a membership** is computed by a
> documented algorithm or decided by a named human.

Nothing in this service writes to an instructor record. Every output is a **draft** that a human
confirms.

---

## Three ways to run the same pipeline

The pipeline never changes. Only the provider behind it does. Switch with one environment variable.

| Scenario | `PROVIDER` | What it uses | When to use it |
|---|---|---|---|
| **API** | `api` | A hosted model over an OpenAI-compatible or Anthropic endpoint | Default for real work. Best quality, no GPU needed |
| **Hugging Face** | `hf` | HF Inference API, or a local `transformers` pipeline | Open models, reproducible, no vendor lock-in |
| **Local** | `local` | Ollama or vLLM on your own machine | Offline work, demo-day contingency, zero cost |
| *(Stub)* | `stub` | Deterministic canned responses | **The default in tests and in UI development.** No network, no spend |

```bash
PROVIDER=api    make run     # hosted
PROVIDER=hf     make run     # hugging face
PROVIDER=local  make run     # ollama / vllm
PROVIDER=stub   make run     # offline, free, deterministic
```

Provider settings live in `config/providers.yaml`. Adding a fourth provider means adding a class in
`app/providers/` and a block in that file — **never** a change inside `app/pipeline/`.

---

## Quick start

```bash
git clone <repo-url>
cd ai-service
cp .env.example .env          # then fill in your key if using PROVIDER=api
make install
make test                     # runs against the stub — no network, no key needed
make run                      # API on http://localhost:8100
make ui                       # Streamlit on http://localhost:8501
```

Docker instead:

```bash
docker compose up --build
```

---

## Repository layout

```
ai-service/
├── app/
│   ├── api/          FastAPI routes — the contract the core API calls
│   ├── providers/    one adapter per scenario: api · hf · local · stub
│   ├── pipeline/     the steps: extract → normalise → redact → model → validate → postprocess
│   ├── prompts/      versioned Jinja templates, reviewed like code
│   ├── schemas/      Pydantic models — the output contract
│   ├── skills/       skill taxonomy and canonicalisation
│   ├── telemetry.py  model version, latency, tokens, cost — on every call
│   └── errors.py
├── config/           settings, provider profiles, logging
├── eval/             labelled datasets, metric runners, reports
├── ui/               Streamlit — an internal tool, never the product
├── tests/            unit · integration · fixtures
├── scripts/          one-off and operational scripts
├── docs/             architecture, decisions, runbook
└── data/             gitignored — never commit a real CV
```

---

## Rules the team agreed to

1. **Nothing in `notebooks/` is imported by `app/`.** A notebook is where you discover something;
   `app/` is where you commit to it.
2. **No secret in the repository, ever.** Keys come from the environment. `make check-secrets`
   runs in CI.
3. **No real CV is committed.** `data/` is gitignored. Test fixtures are synthetic.
4. **Every model output is validated against a Pydantic schema.** Prose parsing is not permitted
   anywhere.
5. **Every AI call is logged** with model version, prompt version, latency, tokens and cost.
6. **Every feature has a kill switch** and the product passes its tests with the feature off.
7. **A feature without a metric cannot be accepted** at a sprint review.

---

## Where to start reading

| You are… | Read |
|---|---|
| New to the project | `docs/ARCHITECTURE.md` then `app/pipeline/run.py` |
| Adding a provider | `app/providers/base.py` then any existing provider |
| Changing a prompt | `app/prompts/templates/` and `docs/PROMPTS.md` |
| Adding an evaluation | `eval/README.md` |
| Debugging a bad output | `app/telemetry.py` then the run id in the logs |
