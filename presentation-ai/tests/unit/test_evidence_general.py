from unittest.mock import MagicMock

from app.pipeline.evidence_general import (
    FACT_CHECK_RESPONSE_SCHEMA,
    MIN_CONFIDENCE_FOR_VERDICT,
    _QUOTA_REASON,
    verify,
)
from app.providers.base import CompletionResult
from app.schemas.presentation import Claim
from app.telemetry import get_session_records, reset_session_records
from config.settings import Settings


def _claim(**overrides):
    base = dict(
        claim_id="C1", slide_number=1, text="PostgreSQL supports JSON columns",
        claim_type="technology", track="objective", importance="medium",
    )
    base.update(overrides)
    return Claim(**base)


def _provider(text: str, sources: list | None = None):
    p = MagicMock()
    p.complete.return_value = CompletionResult(
        text=text, model_version="stub", grounding_sources=sources or [],
    )
    return p


def _prompts():
    prompts = MagicMock()
    prompts.render.return_value = "rendered"
    return prompts


def _gemini_grounding_settings() -> Settings:
    return Settings(search_provider="gemini_grounding")


def test_supported_without_grounding_source_is_downgraded():
    provider = _provider('{"status": "supported", "confidence": 0.99, "reason": "I just know"}')
    result = verify(_claim(), provider, _prompts(), _gemini_grounding_settings())
    assert result.status == "unclear"
    assert "downgraded" in result.reason
    assert result.evidence == []


def test_supported_below_min_confidence_is_downgraded():
    assert MIN_CONFIDENCE_FOR_VERDICT == 0.75
    provider = _provider(
        '{"status": "supported", "confidence": 0.50, "reason": "maybe"}',
        sources=[{"url": "https://example.com/docs", "title": "docs"}],
    )
    result = verify(_claim(), provider, _prompts(), _gemini_grounding_settings())
    assert result.status == "unclear"
    assert "downgraded" in result.reason


def test_supported_with_source_and_high_confidence_keeps_verdict():
    provider = _provider(
        '{"status": "supported", "confidence": 0.90, "reason": "official docs confirm it"}',
        sources=[{"url": "https://www.postgresql.org/docs", "title": "PostgreSQL JSON"}],
    )
    result = verify(_claim(), provider, _prompts(), _gemini_grounding_settings())
    assert result.status == "supported"
    assert result.evidence[0].source_url == "https://www.postgresql.org/docs"


def test_grounding_quota_reason_is_explicit_not_generic_fallback():
    from app.errors import DailyQuotaExceeded
    from app.pipeline.evidence_general import _FALLBACK_REASON

    provider = MagicMock()
    provider.complete.side_effect = DailyQuotaExceeded("simulated")
    result = verify(_claim(), provider, _prompts(), _gemini_grounding_settings())
    assert result.status == "unclear"
    assert result.reason == _QUOTA_REASON
    assert result.reason != _FALLBACK_REASON
    assert "grounding quota" in result.reason.lower()


def test_grounding_telemetry_uses_the_selected_grounding_model():
    from app.errors import DailyQuotaExceeded

    reset_session_records()
    provider = MagicMock()
    provider.name = "api"
    provider.model_for_completion.return_value = "configured-grounding-model"
    provider.complete.side_effect = DailyQuotaExceeded("simulated")

    verify(_claim(), provider, _prompts(), _gemini_grounding_settings())

    records = get_session_records()
    assert records[-1].stage == "evidence_general"
    assert records[-1].model_version == "configured-grounding-model"
    assert provider.model_for_completion.call_args.kwargs == {"use_grounding": True}


def test_tavily_search_context_uses_normal_completion_and_attaches_evidence(monkeypatch):
    provider = _provider(
        '{"status": "supported", "confidence": 0.95, "reason": "The provided documentation confirms it."}'
    )
    provider.name = "api"
    provider.model_for_completion.return_value = "standard-model"
    prompts = _prompts()
    prompts.render.side_effect = lambda *_, **kwargs: f"rendered\n{kwargs.get('search_results', '')}"
    tavily = MagicMock()
    tavily.search.return_value = [{
        "title": "PostgreSQL JSON Functions",
        "url": "https://www.postgresql.org/docs/json.html",
        "content": "PostgreSQL supports JSON and JSONB data types.",
    }]
    monkeypatch.setattr("app.pipeline.evidence_general.TavilySearchProvider", lambda _: tavily)

    result = verify(
        _claim(),
        provider,
        prompts,
        Settings(search_provider="tavily", tavily_api_key="test-key", tavily_max_results=3),
    )

    assert result.status == "supported"
    assert result.verification_basis == "external_source"
    assert result.evidence[0].source_url == "https://www.postgresql.org/docs/json.html"
    assert provider.complete.call_args.kwargs["use_grounding"] is False
    assert provider.complete.call_args.kwargs["response_schema"] == FACT_CHECK_RESPONSE_SCHEMA
    assert prompts.render.call_args.kwargs["version"] == "v2"
    assert "PostgreSQL supports JSON" in prompts.render.call_args.kwargs["search_results"]
    assert "PostgreSQL supports JSON" in provider.complete.call_args.kwargs["prompt"]


def test_tavily_empty_results_reuses_existing_quota_fallback(monkeypatch):
    tavily = MagicMock()
    tavily.search.return_value = []
    monkeypatch.setattr("app.pipeline.evidence_general.TavilySearchProvider", lambda _: tavily)

    result = verify(
        _claim(), MagicMock(), _prompts(), Settings(search_provider="tavily", tavily_api_key="test-key")
    )

    assert result.status == "unclear"
    assert result.verification_error == "search_quota_exhausted"


def test_missing_fact_check_keys_logs_specific_warning_and_returns_unclear(caplog):
    provider = _provider('{"answer": "The supplied source supports the claim."}')

    result = verify(_claim(), provider, _prompts(), _gemini_grounding_settings())

    assert result.status == "unclear"
    assert "missing expected keys for claim C1" in caplog.text
    assert provider.complete.call_args.kwargs["response_schema"] == FACT_CHECK_RESPONSE_SCHEMA
