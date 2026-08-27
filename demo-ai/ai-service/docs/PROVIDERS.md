# PROVIDER PLAYBOOK
## How the same pipeline runs on four different backends

**Project:** AMIT Instructor Hub — AI Service
**Audience:** AI track campers
**Companion:** `docs/ARCHITECTURE.md` · `config/providers.yaml` · `app/providers/`

---

# 1. The idea in one page

The pipeline is the product. The model behind it is a detail.

```
CV bytes → text → normalise → redact → prompt → ??? → validate → postprocess → draft JSON
                                                ▲
                                                └── this is the only thing that changes
```

Everything to the left and right of that box is identical no matter which model answers. The
box is filled by a **provider** — one class, four implementations, chosen by one environment
variable.

```bash
PROVIDER=api    make run   # a hosted model over an OpenAI-compatible or Anthropic endpoint
PROVIDER=hf     make run   # Hugging Face — hosted Inference API, or transformers in-process
PROVIDER=local  make run   # Ollama or vLLM running on your own machine
PROVIDER=stub   make run   # deterministic canned responses — offline, free, instant
```

Nothing else changes. Not the prompt, not the schema, not the redaction, not the tests.

## Why we built it this way

Three situations will happen during this camp, and all three are certain:

1. **Someone will not have an API key on day one.** They still need to build screens and write
   tests. `PROVIDER=stub` lets them work with zero setup and zero spend.
2. **The budget will run low, or a provider will rate-limit us.** `PROVIDER=hf` or
   `PROVIDER=local` keeps the work moving.
3. **Something will go wrong on demo day.** A provider outage, an expired key, a network
   problem in the venue. `PROVIDER=local` with the model already pulled is the contingency,
   and it is only a contingency if it was tested in advance.

Building the adapter first turns all three from emergencies into a configuration change.

## The rule that makes it work

> **Nothing outside `app/providers/` imports a provider SDK.**
> **Nothing inside `app/pipeline/` knows which provider it is talking to.**

If you find yourself writing `if provider == "openai"` inside pipeline code, stop. That
condition belongs in a provider class.

---

# 2. The contract every provider implements

`app/providers/base.py`

```python
@dataclass
class Completion:
    text: str                       # raw text — schema enforcement happens upstream
    model_version: str              # what actually answered, for telemetry
    tokens_in: int = 0
    tokens_out: int = 0
    raw: dict | None = None


class ProviderAdapter(ABC):
    name: str

    async def complete(self, prompt: str, *, schema=None,
                       temperature=0.1, max_tokens=4096,
                       timeout_seconds=60) -> Completion: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    async def healthcheck(self) -> bool: ...

    async def aclose(self) -> None: ...
```

Four methods. That is the entire surface.

**Two design points worth understanding:**

**`complete` returns raw text, not a parsed object.** Schema validation happens once, in
`app/pipeline/run.py`, for every provider. If each provider parsed its own JSON we would have
four subtly different parsers and four different bugs.

**`embed` is separate from `complete`.** Embeddings run once per document, not once per
request, so we self-host BGE-M3 regardless of which text provider is selected. See
`app/providers/embeddings.py`. The hosted provider deliberately raises `NotImplementedError`
on `embed` — that is not an oversight, it is a statement that embeddings are not its job.

---

# 3. Scenario 1 — `api` · hosted

**Use it for:** real work, the default. Best quality, no GPU, no local setup, least prompt
engineering needed.

**File:** `app/providers/api_provider.py`

## Setup

```bash
cp .env.example .env
```

```dotenv
PROVIDER=api
API_BASE_URL=https://api.openai.com/v1
API_KEY=sk-...
API_MODEL=gpt-4o-mini
API_TIMEOUT_SECONDS=45
```

```bash
make run
python scripts/check_env.py     # confirm it is reachable before debugging anything else
```

## How it works

It speaks the OpenAI chat-completions shape over plain `httpx`. No vendor SDK, deliberately —
which means the same class works against **any** endpoint that speaks that shape:

| Provider | `API_BASE_URL` |
|---|---|
| OpenAI | `https://api.openai.com/v1` |
| Azure OpenAI | `https://<resource>.openai.azure.com/openai/deployments/<deployment>` |
| Together | `https://api.together.xyz/v1` |
| Groq | `https://api.groq.com/openai/v1` |
| OpenRouter | `https://openrouter.ai/api/v1` |
| Anthropic | needs a small subclass — different request shape |

Switching between the first five is a one-line change in `.env`.

## What to watch

- **JSON mode is requested but never trusted.** We set `response_format: {"type": "json_object"}`
  *and* validate the result against the Pydantic schema. A provider claiming JSON mode has
  still returned prose in our testing.
- **Spend is capped in code**, not in a spreadsheet. `DAILY_SPEND_CAP_USD` is enforced before
  every billable call. Past the cap, generation refuses with a clear message rather than
  quietly overspending.
- **Redaction runs before every call.** Non-negotiable, and there is an automated test that
  inspects the outbound body.

## Cost

The two tiers matter. Use the small tier by default:

| Tier | Use it for | Rough relative cost |
|---|---|---|
| Small (mini / flash class) | CV extraction, JD drafting, intent classification — high volume, human-reviewed | 1× |
| Frontier | Nothing in this project by default. Escalate only with a written reason in the sprint report | 10–20× |

For the Instructor Hub, **every generative feature is human-reviewed before it reaches a
record**, which is exactly the condition where the small tier is the right answer.

---

# 4. Scenario 2 — `hf` · Hugging Face

**Use it for:** open models, reproducibility, no vendor lock-in, and as the answer when the
budget question comes up.

**File:** `app/providers/hf_provider.py`

## Two modes in one provider

```dotenv
PROVIDER=hf
HF_MODE=inference_api          # or: local_transformers
HF_TOKEN=hf_...                # required for inference_api, not for local
HF_MODEL=Qwen/Qwen2.5-7B-Instruct
HF_DEVICE=cpu                  # or cuda
```

### Mode A — `inference_api`

Calls Hugging Face's hosted endpoint. Needs a token. No local install, no download.

```bash
PROVIDER=hf HF_MODE=inference_api make run
```

### Mode B — `local_transformers`

Loads the model into this process with `transformers`. No token, no network after the first
download, and slow on CPU.

```bash
make install-hf                # installs torch — this is a large download, be patient
PROVIDER=hf HF_MODE=local_transformers make run
```

Expect **30–90 seconds per CV on CPU** for a 7B model. That is usable for testing and
unusable for a live queue. Set `HF_DEVICE=cuda` if a GPU is available.

## The important difference: no JSON mode

Hugging Face endpoints do not support a JSON-mode flag. The model is asked for JSON by the
prompt alone, so **malformed output is more likely here than with the other providers**.

That is not a problem — it is what the repair path in `app/pipeline/run.py` exists for:

```python
extraction, err = _parse(completion.text)
if extraction is None:
    rec.retried = 1
    retry = await provider.complete(prompt + f"\n\nYour previous reply was invalid: {err}\n"
                                             "Return valid JSON only.", schema=CVExtraction)
    extraction, err = _parse(retry.text)
    if extraction is None:
        raise SchemaValidationFailed(...)   # fail loudly, never return partial data
```

**One repair attempt, then fail.** Not three, not a loop. If the model cannot produce valid
JSON twice in a row, retrying a third time burns budget without improving the odds.

Because this path fires more often on `hf`, **testing with `PROVIDER=hf` is the fastest way to
find bugs in your error handling.** Do it deliberately at least once per sprint.

## Model choice

| Model | Params | Arabic | Notes |
|---|---|---|---|
| **Qwen2.5-7B-Instruct** | 7B | Good for its size | **Recommended.** Best Arabic at this scale |
| Aya Expanse 8B | 8B | Strong | Explicitly multilingual — worth benchmarking against Qwen |
| Llama-3.1-8B-Instruct | 8B | Weaker | Well documented, easy to run, but noticeably worse on Arabic |
| Qwen2.5-14B / 32B | 14–32B | Better | Needs a real GPU. Not for laptops |

Verify these names against Hugging Face at the start of Sprint 1 — the model landscape moves
faster than any document.

---

# 5. Scenario 3 — `local` · Ollama or vLLM

**Use it for:** offline work, zero cost, and **the demo-day contingency**.

**File:** `app/providers/local_provider.py`

## Setup with Ollama

```bash
# once, on your machine
curl -fsSL https://ollama.com/install.sh | sh      # macOS/Linux
ollama pull qwen2.5:7b-instruct
ollama serve                                        # usually already running
```

```dotenv
PROVIDER=local
LOCAL_BASE_URL=http://localhost:11434/v1
LOCAL_MODEL=qwen2.5:7b-instruct
LOCAL_TIMEOUT_SECONDS=120
```

```bash
make run
curl http://localhost:11434/v1/models      # verify before you blame the code
```

## Why this class looks almost identical to `api_provider.py`

Both Ollama and vLLM expose an **OpenAI-compatible** endpoint. The only differences are the
base URL, the absence of an API key, and a longer timeout. That similarity is deliberate:
reading the two files side by side is the fastest way to understand the adapter pattern.

## In Docker

`docker-compose.yml` has a commented-out Ollama service. Uncomment it and:

```yaml
environment:
  PROVIDER: local
  LOCAL_BASE_URL: http://ollama:11434/v1
```

Note the hostname changes from `localhost` to the service name `ollama` — the classic mistake
when moving from a laptop to compose.

## Hardware reality

| Setup | 7B model | Verdict |
|---|---|---|
| Laptop CPU, 16 GB RAM | 40–120 s per CV | Works. Painful. Fine for a demo of one CV |
| Laptop with 8 GB VRAM GPU | 5–15 s | Comfortable |
| Server GPU | 2–5 s | Production-like |

**Test this before demo week, not during it.** A contingency that has never been run is not a
contingency.

---

# 6. Scenario 4 — `stub` · the one you will use most

**Use it for:** every test, all UI work, and any time you are debugging something that is not
the model.

**File:** `app/providers/stub_provider.py`

```dotenv
PROVIDER=stub
```

No key. No network. No spend. Instant. **This is the default in the test configuration**, and
CI runs the entire suite against it.

## It returns realistic data

The canned CV response deliberately contains the exact case the project cares about:

```
Skills section:  Python, SQL
Projects:        "Developed a recommendation system using Python, Pandas,
                  Scikit-learn and XGBoost."

Stub returns:    Python (explicit), SQL (explicit),
                 Pandas (inferred), Scikit-learn (inferred), XGBoost (inferred)
```

So the skill-inference behaviour is testable without a model at all.

## It can be told to misbehave

This is the part campers usually miss, and it is the most useful part:

```python
StubProvider()                          # normal
StubProvider(mode="timeout")            # raises ProviderUnavailable
StubProvider(mode="invalid_schema")     # returns broken JSON
```

**Every failure path in the pipeline is testable without waiting for a real failure.** If your
error handling only gets exercised when a real provider breaks, you will find out about the bug
on demo day.

```python
@pytest.mark.asyncio
async def test_timeout_is_handled():
    with pytest.raises(ProviderUnavailable):
        await StubProvider(mode="timeout").complete("hello")
```

## The rule

> **If the test suite does not pass with `PROVIDER=stub`, the test is wrong.**

A test that needs a network call is not a unit test. Move it to `tests/integration/` and mark
it so it does not run in CI.

---

# 7. How the selection actually happens

One function. `app/providers/factory.py`:

```python
def build_provider(settings: Settings) -> ProviderAdapter:
    name = settings.provider

    if name == "stub":
        return StubProvider()

    if name == "api":
        if not settings.api_key:
            raise RuntimeError(
                "PROVIDER=api but API_KEY is empty. Set it in .env, or run with PROVIDER=stub."
            )
        return ApiProvider(settings)

    if name == "hf":
        return HuggingFaceProvider(settings)

    if name == "local":
        return LocalProvider(settings)

    raise ValueError(f"Unknown PROVIDER={name!r}. Use one of: api, hf, local, stub.")
```

Called **once at application startup**, in the lifespan handler in `app/main.py`. The instance
lives on `app.state.provider` for the life of the process.

Two things this buys us:

1. **Configuration errors fail at startup, not at request time.** A missing key crashes the
   service in the first second with a message that says what to do — not in the middle of a
   demo with a 500.
2. **Connection pools are reused.** A new `httpx.AsyncClient` per request would be slow and
   would leak sockets.

---

# 8. How to add a fifth provider

Say you want Google Gemini's native API, which does not speak the OpenAI shape.

**Step 1 — write the class.** `app/providers/gemini_provider.py`

```python
class GeminiProvider(ProviderAdapter):
    name = "gemini"

    def __init__(self, settings: Settings) -> None:
        self._client = httpx.AsyncClient(...)

    async def complete(self, prompt, *, schema=None, **kw) -> Completion:
        # translate to Gemini's request shape
        # translate the response back into a Completion
        ...

    async def embed(self, texts): ...
    async def healthcheck(self): ...
    async def aclose(self): ...
```

**Step 2 — register it in the factory.** Four lines.

**Step 3 — add a block to `config/providers.yaml`** with its cost figures and its quirks.

**Step 4 — add it to the provider contract test.**

```python
@pytest.mark.parametrize("provider_cls", [StubProvider, GeminiProvider])
async def test_satisfies_contract(provider_cls): ...
```

**Step 5 — add the environment variables to `.env.example`.**

**What you do NOT touch:** `app/pipeline/`, `app/schemas/`, `app/prompts/`, the API routes, or
any test that is not about providers. If you find yourself editing those, the abstraction has
been broken and the PR should be rejected.

---

# 9. Telemetry — the same for all four

Every call is recorded with the same fields whichever provider answered:

```python
with record_call("cv_parsing", provider.name, "", prompt_version) as rec:
    completion = await provider.complete(prompt, schema=CVExtraction)
    rec.model_version = completion.model_version
    rec.tokens_in, rec.tokens_out = completion.tokens_in, completion.tokens_out
```

| Field | Why it exists |
|---|---|
| `run_id` | The user reports "the output was wrong". This is how you find that exact call |
| `provider` | Compare quality and latency across scenarios with real numbers |
| `model_version` | What actually answered, not what you think you configured |
| `prompt_version` | A bad output six weeks from now traces to the template that made it |
| `latency_ms` | Which provider is viable for a live queue |
| `tokens_in/out`, `cost_usd` | The AI operations report reads these and nothing else |
| `retried`, `outcome` | How often the repair path fires — the real signal on `hf` |

**No candidate data goes in a telemetry record. Ever.** Not the name, not the CV text, not the
extracted fields.

---

# 10. Which one do I use, and when

| Situation | Provider | Why |
|---|---|---|
| Writing a test | `stub` | Fast, free, deterministic |
| Building a screen | `stub` | Do not spend the budget rendering a UI |
| Checking extraction quality | `api` | Best quality — this is the number you report |
| No key yet | `stub` or `hf` | Neither needs a paid key |
| Budget alert fired | `hf` or `local` | Keeps the work moving at zero cost |
| Testing error handling | `hf` or `stub(mode=...)` | Failure paths fire more often here |
| Demo day, primary | `api` | Fastest and most reliable |
| Demo day, contingency | `local` | Works with no internet — **rehearse it** |
| CI | `stub` | No key in CI, no network flakiness, no cost |

---

# 11. What each camper must be able to do

By the end of Sprint 1, everyone on the AI track should be able to:

- [ ] Run the same CV through all four providers and explain the differences in the output
- [ ] Explain why `complete()` returns raw text rather than a parsed object
- [ ] Add a fifth provider without touching anything in `app/pipeline/`
- [ ] Explain why the stub is the default rather than a fallback
- [ ] Trigger the schema repair path deliberately and show the telemetry it produces
- [ ] Say what happens when the daily spend cap is reached, and where that is enforced
- [ ] Run the local model on their own machine, from a cold start, without help

The last one is the demo-day contingency. If only one person can do it, it is not a
contingency.

---

# 12. Common mistakes

| Mistake | What happens | Fix |
|---|---|---|
| `if provider == "openai"` inside pipeline code | The abstraction is dead and the next provider means a rewrite | Move the condition into a provider class |
| Building the client inside `complete()` | New connection pool per request; sockets leak | Build it in `__init__`, once |
| Trusting JSON mode without validating | Prose reaches the parser and the failure is confusing | Always validate against the schema |
| Retrying three or four times | Burns budget without improving the odds | One repair attempt, then fail loudly |
| Catching the exception and returning `{}` | Silent failure — the worst kind | Raise `SchemaValidationFailed` and let the envelope handle it |
| Writing a test that needs a network call | CI is flaky and slow for everyone | Use the stub; move it to `tests/integration/` if it truly needs a real call |
| Committing `.env` | A key in git history is a security incident, not a mistake | `.gitignore` covers it, `detect-secrets` runs in CI, check anyway |
| Trying `local` for the first time on demo day | It will not work | Rehearse in Sprint 4 |

---

# 13. Quick reference

```bash
# Setup
cp .env.example .env
make install
make install-hf                    # only if you need the hf local mode — installs torch

# Run
PROVIDER=stub  make run            # default: offline, free
PROVIDER=api   make run            # hosted
PROVIDER=hf    make run            # hugging face
PROVIDER=local make run            # ollama / vllm

# Verify
python scripts/check_env.py        # is the selected provider reachable?
curl localhost:8100/health         # per-dependency status

# Test
make test                          # always runs on the stub
PROVIDER=hf pytest tests/integration/   # exercise the repair path deliberately

# UI
make ui                            # streamlit — an internal tool, not the product
```

**Files to read, in order:**

1. `app/providers/base.py` — the contract
2. `app/providers/stub_provider.py` — the simplest implementation
3. `app/providers/api_provider.py` — the real one
4. `app/providers/local_provider.py` — almost the same, on purpose
5. `app/providers/factory.py` — how one gets chosen
6. `app/pipeline/run.py` — where it is used, and where the schema repair lives
