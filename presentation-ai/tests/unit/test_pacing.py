"""Pacing and rate-limiting tests.

Centralized pacing in api_provider guarantees that consecutive Gemini round-trips
are paced consistently across all pipeline stages without arbitrary double sleeps.
"""
from unittest.mock import MagicMock

from app.pipeline.fact_check import verify_claims
from app.providers import api_provider
from app.providers.api_provider import parse_retry_delay_seconds, wait_for_gemini_pacing
from app.schemas.presentation import Claim, ClaimVerification
from config.settings import Settings


class _PacingSettings:
    gemini_call_pacing_seconds = 3.0


def test_wait_for_gemini_pacing_skips_first_then_waits_remainder(monkeypatch):
    class Clock:
        def __init__(self) -> None:
            self.t = 100.0

        def monotonic(self) -> float:
            return self.t

    clock = Clock()
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.t += seconds

    monkeypatch.setattr(api_provider.time, "sleep", fake_sleep)
    monkeypatch.setattr(api_provider.time, "monotonic", clock.monotonic)
    api_provider._last_gemini_call_at = 0.0

    wait_for_gemini_pacing(3.0)
    assert sleeps == []

    clock.t += 0.5
    wait_for_gemini_pacing(3.0)
    assert sleeps == [2.5]


def test_parse_retry_delay_seconds_from_google_payload():
    details = {
        "error": {
            "code": 429,
            "status": "RESOURCE_EXHAUSTED",
            "details": [
                {"quotaValue": "10", "quotaMetric": "generate_content_free_tier_requests"},
                {"retryDelay": "8s"},
            ],
        }
    }
    assert parse_retry_delay_seconds(details) == 8.0
    assert parse_retry_delay_seconds({"retryDelay": 12}) == 12.0
    assert parse_retry_delay_seconds({}) is None


def test_verify_claims_has_no_duplicate_sleeps(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

    mock_verify = MagicMock(
        return_value=ClaimVerification(
            claim_id="x", status="project_unsupported", confidence=0.5, reason="ok", evidence=[],
        )
    )
    monkeypatch.setattr("app.pipeline.fact_check.plausibility.verify", mock_verify)

    claims = [
        Claim(claim_id="C1", slide_number=1, text="x", claim_type="performance", track="project_specific", importance="high"),
        Claim(claim_id="C2", slide_number=1, text="y", claim_type="performance", track="project_specific", importance="high"),
    ]

    verifications = verify_claims(
        claims, MagicMock(), MagicMock(), {1: "ctx"}, Settings(search_provider="gemini_grounding")
    )
    assert len(verifications) == 2
    # No duplicate sleeps inside fact_check.py (pacing is centralized in api_provider.py)
    assert sleeps == []
