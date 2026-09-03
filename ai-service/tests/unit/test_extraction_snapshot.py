from app.pipeline import run
from app.schemas.cv import CVSchema


def test_same_cleaned_content_reuses_validated_snapshot(monkeypatch) -> None:
    run._snapshot_cache.clear()
    calls = 0

    def fake_query_model(system_prompt, user_prompt, validate_fn, metadata):
        nonlocal calls
        calls += 1
        metadata.update(
            {
                "model_used": "test-model",
                "provider": "test-provider",
                "attempt_number": 1,
                "fallback_occurred": False,
            }
        )
        return CVSchema(skills=["Python"])

    monkeypatch.setattr(run, "query_model", fake_query_model)

    first = run.clean_and_query("Python")
    first_metadata = run.get_extraction_metadata()
    second = run.clean_and_query("Python")
    second_metadata = run.get_extraction_metadata()

    assert first == second
    assert calls == 1
    assert first_metadata["cache_hit"] is False
    assert second_metadata["cache_hit"] is True


def test_snapshot_key_changes_when_model_configuration_changes(monkeypatch) -> None:
    run._snapshot_cache.clear()
    calls = 0

    def fake_query_model(system_prompt, user_prompt, validate_fn, metadata):
        nonlocal calls
        calls += 1
        return CVSchema(skills=["Python"])

    monkeypatch.setattr(run, "query_model", fake_query_model)
    monkeypatch.setattr(run.config, "MODEL_CHAIN", [{"repo_id": "model-a", "provider": "provider-a"}])
    run.clean_and_query("Python")
    monkeypatch.setattr(run.config, "MODEL_CHAIN", [{"repo_id": "model-b", "provider": "provider-a"}])
    run.clean_and_query("Python")

    assert calls == 2


def test_snapshot_expires(monkeypatch) -> None:
    run._snapshot_cache.clear()
    monkeypatch.setattr(run, "SNAPSHOT_TTL_SECONDS", 0.0)
    calls = 0

    def fake_query_model(system_prompt, user_prompt, validate_fn, metadata):
        nonlocal calls
        calls += 1
        return CVSchema(skills=["Python"])

    monkeypatch.setattr(run, "query_model", fake_query_model)
    run.clean_and_query("Python")
    run.clean_and_query("Python")

    assert calls == 2


def test_snapshot_evicts_oldest_entry(monkeypatch) -> None:
    run._snapshot_cache.clear()
    monkeypatch.setattr(run, "SNAPSHOT_MAX_ENTRIES", 1)
    monkeypatch.setattr(
        run,
        "query_model",
        lambda system_prompt, user_prompt, validate_fn, metadata: CVSchema(
            skills=["Python"]
        ),
    )

    run.clean_and_query("Python")
    run.clean_and_query("SQL")

    assert len(run._snapshot_cache) == 1
