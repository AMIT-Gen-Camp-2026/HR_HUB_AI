from app.providers import hf_provider


def test_query_model_reports_actual_fallback_metadata(monkeypatch) -> None:
    attempts = []

    def fake_call(repo_id, provider, system_prompt, user_prompt):
        attempts.append(repo_id)
        if len(attempts) == 1:
            raise hf_provider.ModelInferenceError("primary unavailable")
        return "validated"

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
