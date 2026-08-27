# Runbook

## The service will not start

| Symptom | Cause | Fix |
|---|---|---|
| `RuntimeError: PROVIDER=api but API_KEY is empty` | No key in `.env` | Add the key, or run `PROVIDER=stub` |
| `No prompt templates found` | Wrong working directory | Run from `ai-service/` |
| `ModuleNotFoundError: transformers` | HF extras not installed | `make install-hf` |

## The output is wrong

1. Find the `run_id` in the response or the logs.
2. Grep the logs for that id — you get the model version, the prompt version and the timing.
3. Reproduce with the same prompt version. If you cannot reproduce it, the temperature is
   too high; extraction should run at 0.1 or lower.

## The local provider is unreachable

```bash
ollama list                       # is the model pulled?
ollama pull qwen2.5:7b-instruct
curl http://localhost:11434/v1/models
python scripts/check_env.py
```

## Demo day contingency

1. `PROVIDER=local` with the model already pulled — test this **before** the day.
2. If that fails, turn every AI feature off. The product must still complete every
   Must-have journey. That is the release gate, and it is tested every sprint.
