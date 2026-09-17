"""Unit tests for PR_BUG_003: claim deduplication via rapidfuzz."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.pipeline.claim_extraction import (
    RawClaimOutput,
    _deduplicate_claims,
    extract_claims,
)
from app.pipeline.extract_pptx import SlideContent, SlideElement
from config.settings import Settings


# ---------------------------------------------------------------------------
# _deduplicate_claims() unit tests
# ---------------------------------------------------------------------------

def _make_raw(text: str, claim_type: str = "capability", slide_number: int = 1):
    """Helper: create a (RawClaimOutput, slide_number) pair."""
    return (RawClaimOutput(slide_number=slide_number, text=text, claim_type=claim_type), slide_number)


def test_dedup_removes_exact_duplicate_same_type():
    """Exact same text + claim_type on two slides -> second is dropped."""
    items = [
        _make_raw("We built a real-time dashboard", "capability", 1),
        _make_raw("We built a real-time dashboard", "capability", 3),
    ]
    result = _deduplicate_claims(items, threshold=90)
    assert len(result) == 1
    assert result[0][1] == 1  # first occurrence kept


def test_dedup_removes_near_duplicate_same_type():
    """Near-identical text (>90 similarity) + same claim_type -> duplicate removed."""
    items = [
        _make_raw("We achieved 98% accuracy on the test set.", "performance", 1),
        _make_raw("We achieved 98% accuracy on the test set", "performance", 2),  # no trailing dot
    ]
    result = _deduplicate_claims(items, threshold=90)
    assert len(result) == 1


def test_dedup_keeps_same_text_different_type():
    """Same text but DIFFERENT claim_type -> both are kept (per spec)."""
    items = [
        _make_raw("Our model runs at 50ms latency", "performance", 1),
        _make_raw("Our model runs at 50ms latency", "capability", 2),
    ]
    result = _deduplicate_claims(items, threshold=90)
    assert len(result) == 2


def test_dedup_threshold_zero_disables_dedup():
    """threshold=0 -> deduplication skipped entirely, all claims returned."""
    items = [
        _make_raw("Same claim text", "capability", 1),
        _make_raw("Same claim text", "capability", 2),
        _make_raw("Same claim text", "capability", 3),
    ]
    result = _deduplicate_claims(items, threshold=0)
    assert len(result) == 3  # nothing removed


def test_dedup_aggressive_threshold_50():
    """threshold=50 -> more aggressive; moderately similar claims are deduplicated."""
    items = [
        _make_raw("We used machine learning to classify images.", "capability", 1),
        _make_raw("We used ML to classify images.", "capability", 2),  # ~70 similarity
    ]
    result = _deduplicate_claims(items, threshold=50)
    assert len(result) == 1


def test_dedup_different_claims_all_kept():
    """Completely distinct claims are never deduplicated."""
    items = [
        _make_raw("Our model achieves 99% accuracy", "performance", 1),
        _make_raw("The project used React for the frontend", "capability", 2),
        _make_raw("Team size was 5 people over 3 months", "project_specific", 3),
    ]
    result = _deduplicate_claims(items, threshold=90)
    assert len(result) == 3


def test_dedup_triplicate_only_first_kept():
    """Three copies of same claim -> only first is kept."""
    items = [
        _make_raw("Accuracy reached 95%", "performance", 1),
        _make_raw("Accuracy reached 95%", "performance", 4),
        _make_raw("Accuracy reached 95%", "performance", 7),
    ]
    result = _deduplicate_claims(items, threshold=90)
    assert len(result) == 1
    assert result[0][1] == 1


# ---------------------------------------------------------------------------
# extract_claims() integration: IDs are sequential after deduplication
# ---------------------------------------------------------------------------

def test_claim_ids_sequential_after_dedup():
    """After deduplication, claim IDs must be CLM-001, CLM-002, ... with no gaps."""
    slides = [
        SlideContent(slide_number=1, title="S1", elements=[SlideElement(type="text", content="Slide 1 text")]),
        SlideContent(slide_number=2, title="S2", elements=[SlideElement(type="text", content="Slide 2 text")]),
        SlideContent(slide_number=3, title="S3", elements=[SlideElement(type="text", content="Slide 3 text")]),
    ]

    # Each batch is one slide (batch_size=1). Slides 1 and 3 emit identical claims;
    # slide 2 emits a unique claim.  After dedup: 2 claims total -> CLM-001, CLM-002.
    def mock_complete(prompt, response_schema=None, **kwargs):
        if "Slide 2" in prompt:
            payload = [{"slide_number": 2, "text": "Unique claim here", "claim_type": "capability",
                        "track": "project_specific"}]
        else:
            payload = [{"slide_number": 1, "text": "Repeated claim", "claim_type": "performance",
                        "track": "project_specific"}]
        return MagicMock(text=json.dumps(payload), model_version="mock", tokens_in=5, tokens_out=5)

    mock_provider = MagicMock()
    mock_provider.name = "mock"
    mock_provider.complete.side_effect = mock_complete

    prompts = MagicMock()
    prompts.render.side_effect = lambda *a, slides, **kw: " ".join(s["slide_text"] for s in slides)

    settings = MagicMock(spec=Settings)
    settings.gemini_call_pacing_seconds = 0.0
    settings.claim_extraction_batch_size = 1  # one slide per batch so prompt contains slide text
    settings.claim_deduplication_threshold = 90

    with patch("app.pipeline.claim_extraction.get_settings", return_value=settings):
        claims, failed = extract_claims(slides, mock_provider, prompts)

    ids = [c.claim_id for c in claims]
    assert ids == ["CLM-001", "CLM-002"], f"Unexpected IDs: {ids}"
    assert failed == []


def test_claim_dedup_disabled_via_threshold_zero_in_pipeline():
    """With threshold=0, identical claims from different slide batches are NOT deduplicated."""
    slides = [
        SlideContent(slide_number=1, title="A", elements=[SlideElement(type="text", content="text A")]),
        SlideContent(slide_number=2, title="B", elements=[SlideElement(type="text", content="text B")]),
    ]

    def mock_complete(prompt, response_schema=None, **kwargs):
        # Both batches return a claim with identical text + type.
        return MagicMock(
            text=json.dumps([{"slide_number": 1, "text": "Repeated claim", "claim_type": "capability",
                              "track": "project_specific"}]),
            model_version="mock", tokens_in=5, tokens_out=5,
        )

    mock_provider = MagicMock()
    mock_provider.name = "mock"
    mock_provider.complete.side_effect = mock_complete

    prompts = MagicMock()
    prompts.render.return_value = "rendered"

    settings = MagicMock(spec=Settings)
    settings.gemini_call_pacing_seconds = 0.0
    settings.claim_extraction_batch_size = 1  # one slide per batch -> 2 LLM calls -> 2 raw claims
    settings.claim_deduplication_threshold = 0  # disabled: keep all duplicates

    with patch("app.pipeline.claim_extraction.get_settings", return_value=settings):
        claims, _ = extract_claims(slides, mock_provider, prompts)

    # With threshold=0, both copies are kept.
    assert len(claims) == 2
    assert claims[0].claim_id == "CLM-001"
    assert claims[1].claim_id == "CLM-002"