"""Unit tests for empty/image-only presentation handling (PR_BUG_001)."""
from __future__ import annotations

import fitz
import pytest

from app.pipeline.run import run_presentation_analysis
from app.prompts.registry import PromptRegistry
from app.providers.stub_provider import StubProvider
from config.settings import Settings


def _create_image_only_pdf() -> bytes:
    doc = fitz.open()
    doc.new_page()  # Page with no text
    content = doc.tobytes()
    doc.close()
    return content


def _create_mixed_pdf() -> bytes:
    doc = fitz.open()
    doc.new_page()  # Empty page 1
    p2 = doc.new_page()  # Text page 2
    p2.insert_text((50, 50), "PostgreSQL supports JSON columns.")
    content = doc.tobytes()
    doc.close()
    return content


def _create_normal_pdf() -> bytes:
    doc = fitz.open()
    p1 = doc.new_page()
    p1.insert_text((50, 50), "PostgreSQL supports JSON columns.")
    p2 = doc.new_page()
    p2.insert_text((50, 50), "FastAPI is built on Starlette.")
    content = doc.tobytes()
    doc.close()
    return content


def test_image_only_presentation_scores_zero_and_no_extractable_content():
    settings = Settings(enable_result_cache=False)
    provider = StubProvider(settings)
    prompts = PromptRegistry(settings.prompts_dir)
    content = _create_image_only_pdf()

    result = run_presentation_analysis(
        filename="image_only.pdf",
        content=content,
        provider=provider,
        prompts=prompts,
        settings=settings,
    )

    assert result.completeness.status == "no_extractable_content"
    assert result.completeness.slides_failed == 1
    assert result.completeness.slides_processed == 0
    assert result.completeness.message is not None
    assert "no text content" in result.completeness.message.lower()

    assert result.scores.overall == 0
    assert result.scores.fact_accuracy == 0
    assert result.scores.verified_ratio == 0
    assert result.scores.evidence_coverage == 0
    assert result.scores.claim_reliability == 0


def test_mixed_presentation_partial_completeness():
    settings = Settings(enable_result_cache=False)
    provider = StubProvider(settings)
    prompts = PromptRegistry(settings.prompts_dir)
    content = _create_mixed_pdf()

    result = run_presentation_analysis(
        filename="mixed.pdf",
        content=content,
        provider=provider,
        prompts=prompts,
        settings=settings,
    )

    assert result.completeness.status == "partial"
    assert result.completeness.slides_failed == 1
    assert result.completeness.slides_processed == 1
    assert result.presentation.slide_count == 2


def test_normal_presentation_ok_completeness():
    settings = Settings(enable_result_cache=False)
    provider = StubProvider(settings)
    prompts = PromptRegistry(settings.prompts_dir)
    content = _create_normal_pdf()

    result = run_presentation_analysis(
        filename="normal.pdf",
        content=content,
        provider=provider,
        prompts=prompts,
        settings=settings,
    )

    assert result.completeness.status == "ok"
    assert result.completeness.slides_failed == 0
    assert result.completeness.slides_processed == 2
    assert result.presentation.slide_count == 2
