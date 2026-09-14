# Runbook

## Run Locally

```bash
make install
cp .env.example .env      # set PROVIDER=stub to run fully offline first
make run
```

## Smoke Test (Offline / No External Calls)

With `PROVIDER=stub` in `.env`:

```bash
curl -X POST http://localhost:8100/api/v1/presentation/analyze \
  -F "file=@data/test_presentations/sample.pptx"
```

Returns a valid `PresentationAnalysisResult` JSON with canned claims, confirming that the Flask app, routing, extraction, and pipeline wiring work before any external AI calls are made.

## Switch to Production Gemini

1. Obtain an API key from Google AI Studio or Vertex AI.
2. In `.env`:
   ```env
   PROVIDER=api
   GEMINI_API_KEY=your_gemini_api_key_here
   GEMINI_MODEL=gemini-3.5-flash-lite
   ```
3. Run `make run`.

## Run Evaluation Benchmark

To run the full evaluation suite against the 12-presentation labeled benchmark dataset:

```bash
.venv\Scripts\python eval/runners/run_extraction.py --dataset eval/datasets/presentation-extraction/v1 --prompt-version v3
```

Results (including extraction F1, track accuracy, claim_type accuracy, Track B verification metrics, and stage-level token metrics) will be output to console and persisted in `eval/results/`.

## Common Errors & Remediation

| Symptom | Likely Cause | Remediation |
|---|---|---|
| `RuntimeError: GEMINI_API_KEY is required` | `PROVIDER=api` but key missing in `.env` | Set `GEMINI_API_KEY` in `.env`. |
| `429` / `DAILY_QUOTA_EXCEEDED` | Hit the free-tier daily request cap (500 RPD) | Switch to a paid API key or Vertex AI tier in `.env`. |
| `contradicted` verdict with empty `evidence` | Guardrail failure | Should never happen — `evidence_general.py` force-downgrades to `unclear`. |
| `UNSUPPORTED_FORMAT` / `CORRUPTED_FILE` | Uploaded file is not a valid `.pptx` | Ensure file is a valid PowerPoint document starting with `PK\x03\x04` magic bytes. |
| `FILE_TOO_LARGE` | Uploaded file exceeds 25MB limit | Compress media inside presentation or increase `MAX_CONTENT_LENGTH`. |

## Adding a New Pipeline Stage

1. Add the module under `app/pipeline/`, marking its docstring as deterministic or AI-backed.
2. Wire it into `app/pipeline/run.py`.
3. Add a unit test in `tests/unit/`.
4. If AI-backed, ensure all model calls go through `with record_call(...)` for token telemetry.
5. If modifying claim schemas or status lists, update `docs/DECISIONS.md` and `docs/INTEGRATION_REFERENCE.md`.
