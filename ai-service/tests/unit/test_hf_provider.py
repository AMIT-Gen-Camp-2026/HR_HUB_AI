import pytest
from app.providers import hf_provider


def test_query_model_reports_actual_fallback_metadata(monkeypatch) -> None:
    attempts = []

    def fake_call(repo_id, provider, system_prompt, user_prompt):
        attempts.append(repo_id)
        if len(attempts) == 1:
            raise hf_provider.ModelInferenceError("primary unavailable")
        return "validated"

    monkeypatch.setattr(hf_provider.config, "EXTRACTION_PROVIDER", "hf")
    monkeypatch.setattr(
        hf_provider.config,
        "MODEL_CHAIN",
        [
            {"repo_id": "primary-model", "provider": "provider-a"},
            {"repo_id": "fallback-model", "provider": "provider-b"},
        ],
    )
    monkeypatch.setattr(hf_provider, "_call_model", fake_call)
    metadata = {}

    result = hf_provider.query_model("system", "user", metadata=metadata)

    assert result == "validated"
    assert attempts == ["primary-model", "fallback-model"]
    assert metadata == {
        "model_used": "fallback-model",
        "provider": "provider-b",
        "attempt_number": 2,
        "fallback_occurred": True,
    }


def test_query_model_auto_chain_fallback_across_providers(monkeypatch) -> None:
    attempts = []

    def fake_call(repo_id, provider, system_prompt, user_prompt):
        attempts.append((repo_id, provider))
        if provider == "gemini":
            raise hf_provider.ModelInferenceError("gemini quota exceeded (402/429)")
        return "groq-success"

    monkeypatch.setattr(hf_provider.config, "EXTRACTION_PROVIDER", "auto")
    monkeypatch.setattr(hf_provider.config, "GEMINI_API_KEY", "fake-gemini-key")
    monkeypatch.setattr(hf_provider.config, "GROQ_API_KEY", "fake-groq-key")
    monkeypatch.setattr(hf_provider, "_call_model", fake_call)
    metadata = {}

    result = hf_provider.query_model("system", "user", metadata=metadata)

    assert result == "groq-success"
    assert attempts == [
        (hf_provider.config.GEMINI_EXTRACTION_MODEL, "gemini"),
        (hf_provider.config.GROQ_EXTRACTION_MODEL, "groq"),
    ]
    assert metadata["fallback_occurred"] is True
    assert metadata["provider"] == "groq"


def test_query_model_validation_failure_triggers_fallback(monkeypatch) -> None:
    calls = []

    def fake_call(repo_id, provider, system_prompt, user_prompt):
        calls.append(provider)
        if provider == "gemini":
            return "{truncated json"
        return '{"valid": true}'

    def validator(raw_text):
        if not raw_text.endswith("}"):
            raise ValueError("Unbalanced braces")
        return {"valid": True}

    monkeypatch.setattr(hf_provider.config, "EXTRACTION_PROVIDER", "auto")
    monkeypatch.setattr(hf_provider.config, "GEMINI_API_KEY", "fake-key")
    monkeypatch.setattr(hf_provider.config, "GROQ_API_KEY", "fake-key")
    monkeypatch.setattr(hf_provider, "_call_model", fake_call)

    metadata = {}
    result = hf_provider.query_model("sys", "usr", validate_fn=validator, metadata=metadata)

    assert result == {"valid": True}
    assert calls == ["gemini", "groq"]
    assert metadata["provider"] == "groq"
    assert metadata["fallback_occurred"] is True


def test_call_model_dispatch(monkeypatch) -> None:
    monkeypatch.setattr(hf_provider, "_call_gemini", lambda model, sys, usr: f"gemini:{model}")
    monkeypatch.setattr(
        hf_provider,
        "_call_openai_compatible",
        lambda prov, model, base, key, sys, usr, extra=None: f"{prov}:{model}",
    )
    monkeypatch.setattr(hf_provider, "_call_hf", lambda repo, prov, sys, usr: f"hf:{repo}@{prov}")

    assert hf_provider._call_model("gemini-3.6-flash", "gemini", "sys", "usr") == "gemini:gemini-3.6-flash"
    assert hf_provider._call_model("llama-3", "groq", "sys", "usr") == "groq:llama-3"
    assert hf_provider._call_model("llama-3", "openrouter", "sys", "usr") == "openrouter:llama-3"
    assert hf_provider._call_model("qwen", "featherless-ai", "sys", "usr") == "hf:qwen@featherless-ai"
