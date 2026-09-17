import json
from unittest.mock import MagicMock, patch

import pytest

from app.pipeline.claim_extraction import (
    RawClaimOutput,
    _chunk,
    extract_claims,
)
from app.pipeline.extract_pptx import SlideContent, SlideElement
from app.prompts.registry import PromptRegistry
from config.settings import Settings, get_settings


def test_chunk_helper():
    items = [1, 2, 3, 4, 5, 6, 7]
    chunks = _chunk(items, 3)
    assert chunks == [[1, 2, 3], [4, 5, 6], [7]]
    assert _chunk([], 4) == []


def test_claim_extract_v4_rendering():
    prompts = PromptRegistry(get_settings().prompts_dir)
    slides = [
        {"slide_number": 1, "slide_text": "[Text] First slide content"},
        {"slide_number": 2, "slide_text": "[Text] Second slide content"},
    ]
    rendered = prompts.render("claim_extract", version="v4", slides=slides)
    assert "### Slide 1" in rendered
    assert "### Slide 2" in rendered
    assert "<<<PRESENTATION_CONTENT_START>>>" in rendered
    assert "<<<PRESENTATION_CONTENT_END>>>" in rendered
    assert "content in one slide must never influence classification" in rendered.lower()
    assert "slide_number: integer matching" in rendered


def test_extract_claims_batching_respects_batch_size():
    slides = [
        SlideContent(slide_number=i, title=f"Slide {i}", elements=[SlideElement(type="text", content=f"Slide text {i}")])
        for i in range(1, 8)
    ]

    call_counter = {"n": 0}

    def _distinct_per_batch(prompt, response_schema=None, **kwargs):
        """Return a unique claim per batch so dedup does not collapse them."""
        call_counter["n"] += 1
        return MagicMock(
            text=json.dumps([
                {
                    "slide_number": call_counter["n"],
                    "text": f"Unique claim for batch {call_counter['n']}",
                    "claim_type": "performance",
                    "track": "project_specific",
                }
            ]),
            model_version="mock-v1",
            tokens_in=10,
            tokens_out=10,
        )

    mock_provider = MagicMock()
    mock_provider.name = "mock"
    mock_provider.complete.side_effect = _distinct_per_batch

    prompts = MagicMock()
    prompts.render.return_value = "rendered prompt"

    settings = MagicMock(spec=Settings)
    settings.gemini_call_pacing_seconds = 0.0
    settings.claim_extraction_batch_size = 3
    settings.claim_deduplication_threshold = 0  # disabled so distinct claims are not collapsed

    with patch("app.pipeline.claim_extraction.get_settings", return_value=settings):
        claims, failed_slides = extract_claims(slides, mock_provider, prompts)

    assert mock_provider.complete.call_count == 3  # 7 slides chunked into batches of 3: [3, 3, 1]
    assert failed_slides == []
    assert len(claims) == 3


def test_extract_claims_batch_failure_adds_all_batch_slides_to_failed():
    slides = [
        SlideContent(slide_number=1, title="S1", elements=[SlideElement(type="text", content="Text 1")]),
        SlideContent(slide_number=2, title="S2", elements=[SlideElement(type="text", content="Text 2")]),
    ]

    mock_provider = MagicMock()
    mock_provider.name = "mock"
    mock_provider.complete.side_effect = RuntimeError("Batch failed")

    prompts = MagicMock()
    prompts.render.return_value = "rendered prompt"

    settings = MagicMock(spec=Settings)
    settings.gemini_call_pacing_seconds = 0.0
    settings.claim_extraction_batch_size = 4

    with patch("app.pipeline.claim_extraction.get_settings", return_value=settings):
        claims, failed_slides = extract_claims(slides, mock_provider, prompts)

    assert claims == []
    assert failed_slides == [1, 2]
