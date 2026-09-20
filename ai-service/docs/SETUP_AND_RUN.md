# Setup and Run

This guide describes the current runnable service: Flask API, Hugging Face CV extraction, taxonomy-gated Gemini/Groq/OpenRouter ranking, Streamlit UI, and in-memory process-local caching.

## Prerequisites

- Python 3.11 or newer. The Docker image uses Python 3.11.
- Docker Engine with Docker Compose v2 for the primary path.
- On Windows, use PowerShell or WSL. The local commands below use PowerShell syntax; use `.venv/bin/...` instead of `.venv\Scripts\...` in WSL/Linux.
- Network access and a Hugging Face token for CV extraction. Judge provider keys are needed for ranking.

## Environment

From `ai-service/`, create the environment file:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and set at least:

```dotenv
HF_API_TOKEN=hf_...
GEMINI_API_KEY=...
```

`HF_API_TOKEN` is required by `config.validate()` and the extraction provider. `GEMINI_API_KEY`, `GROQ_API_KEY`, and `OPENROUTER_API_KEY` enable the corresponding judge providers; the configured chain is Gemini, then Groq, then OpenRouter. At least one judge key is needed for ranking.

The following names are the environment variables read by `config/settings.py`:

| Variable | Required | Default / purpose |
|---|---|---|
| `AI_SERVICE_API_KEY` | Optional | Empty; protects API routes when set |
| `GEMINI_API_KEY` | Optional provider key | Empty |
| `GROQ_API_KEY` | Optional provider key | Empty |
| `OPENROUTER_API_KEY` | Optional provider key | Empty |
| `GEMINI_JUDGE_MODEL` | Optional | `gemini-3.8-flash` |
| `GROQ_JUDGE_MODEL` | Optional | `openai/gpt-oss-120b` |
| `OPENROUTER_JUDGE_MODEL` | Optional | `meta-llama/llama-3.3-70b-instruct:free` |
| `GROQ_BASE_URL` | Optional | `https://api.groq.com/openai/v1` |
| `OPENROUTER_BASE_URL` | Optional | `https://openrouter.ai/api/v1` |
| `OPENROUTER_SITE_URL` | Optional | `http://localhost` |
| `JUDGE_TIMEOUT_SECONDS` | Optional | `60` |
| `CACHE_TTL_SECONDS` | Optional | `3600` |
| `CACHE_MAX_ENTRIES` | Optional | `128` |
| `HF_API_TOKEN` | Required for extraction | Empty |
| `HF_MODEL_ID_1` | Optional | `Qwen/Qwen2.5-3B-Instruct` |
| `HF_PROVIDER_1` | Optional | `featherless-ai` |
| `HF_MODEL_ID_2` | Optional | `mistralai/Mistral-7B-Instruct-v0.2` |
| `HF_PROVIDER_2` | Optional | `featherless-ai` |
| `FLASK_DEBUG` | Optional | `False` |
| `FLASK_PORT` | Optional | `5000` |
| `UPLOAD_FOLDER` | Optional | `data` |
| `MAX_NEW_TOKENS` | Optional | `4096` |
| `MODEL_TIMEOUT_SECONDS` | Optional | `60` |
| `RANKING_ENABLED` | Optional | `True` |

The separate `Settings` class used by `app/providers/embeddings.py` reads these aliases:

| Variable | Default / purpose |
|---|---|
| `EMBEDDING_PROVIDER` | `local` |
| `EMBEDDING_MODEL` | `BAAI/bge-m3` |
| `EMBEDDING_DEVICE` | `cpu` |
| `EMBEDDING_API_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| `EMBEDDING_API_MODEL` | `gemini-embedding-001` |
| `GEMINI_API_KEY` | Used as the embedding API key too |

`EMBEDDING_PROVIDER=local` requires the optional `hf` dependency group and downloads a local model. The current authoritative ranking score does not use embeddings. The API embedding path is available for diagnostics.

## Docker Compose

This is the primary supported path. From `ai-service/`:

```powershell
docker compose up --build -d
```

Compose starts:

- API: `http://localhost:5000`
- Streamlit UI: `http://localhost:8501`

Check container state and health:

```powershell
docker compose ps
docker compose logs ai-service
docker compose logs ui
```

The API image health check calls `GET /api/v1/health`. Stop the stack with:

```powershell
docker compose down
```

The UI receives `AI_SERVICE_URL=http://ai-service:5000` inside Compose. Do not change it to `localhost` inside the container; `localhost` there means the UI container itself.

## Local Development

From `ai-service/` in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -e ".[dev,ui]"
```

The local API uses the `.env` values and listens on port 5000 by default:

```powershell
python -m app.main
```

In a second terminal, from `ai-service/`, start Streamlit:

```powershell
.\.venv\Scripts\Activate.ps1
streamlit run ui/streamlit_app.py
```

The API and UI can also be run separately without Docker.

## Verify the Service

Health check:

```powershell
curl.exe http://localhost:5000/api/v1/health
```

Expected response:

```json
{"status":"ok"}
```

The evaluation route accepts multipart form data. `file` must be a real `.pdf` or `.docx`, and `job_description` must be a JSON string. When `AI_SERVICE_API_KEY` is set, include the matching header:

```powershell
curl.exe -X POST "http://localhost:5000/api/v1/cv/evaluate" `
  -H "X-API-Key: $env:AI_SERVICE_API_KEY" `
  -F "file=@candidate.pdf" `
  -F 'job_description={"title":"Data Analyst","required_skills":["Python","SQL"],"nice_to_have_skills":["Tableau"]}'
```

Alternatively, open `http://localhost:8501`, upload a PDF or DOCX, enter one skill or requirement per line, and select **Evaluate CV**. The ranking result shows `skill_evaluations`, the actual `judge_provider`/`judge_model`, the score breakdown, and extraction cache status when available.

A successful response has `success: true`, `extraction_status: "SUCCESS"`, a populated `cv`, and a `ranking` object. Ranking can be `null` when `RANKING_ENABLED=False` or extraction is empty. The second identical request can report `cache_hit: true` in `extraction_metadata`.

## Troubleshooting

### Gemini returns 503

Gemini can temporarily return HTTP 503 with `UNAVAILABLE` and a message about high demand. `GeminiJudgeProvider` retries 503 responses for the same model after 1, 2, and 4 seconds. If all retries fail, the chain continues to Groq and then OpenRouter. This is expected provider availability behavior; check the returned `judge_provider` and `judge_model` to see which provider answered.

### API returns 401

Set `AI_SERVICE_API_KEY` consistently in the API and caller environment, then send it as `X-API-Key`. If the variable is empty, local development intentionally allows the route without a key.

### API returns 502 during extraction

Check `HF_API_TOKEN`, the configured `HF_MODEL_ID_1`/`HF_PROVIDER_1` pair, and the fallback pair. Review `docker compose logs ai-service` or the local Flask logs.

### API returns 502 during ranking

Confirm at least one judge key is configured. Check Gemini 503 messages and the Groq/OpenRouter response in the logs. A malformed judge response, wrong requirement count, requirement mismatch, or evidence quote not present in candidate evidence is rejected by design.

### UI cannot reach the API

For Docker Compose, confirm the UI has `AI_SERVICE_URL=http://ai-service:5000` and both containers are running. For local processes, use the default `http://127.0.0.1:5000` or set `AI_SERVICE_URL` to another reachable API URL before starting Streamlit.
