"""Unit tests for result caching and temperature settings (PR_BUG_004)."""
from __future__ import annotations

import fitz
import pytest

from app.pipeline import run
from app.pipeline.run import _RESULT_CACHE, run_presentation_analysis
from app.prompts.registry import PromptRegistry
from app.providers.stub_provider import StubProvider
from config.settings import Settings


def _create_pdf_content(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), text)
    content = doc.tobytes()
    doc.close()
    return content


@pytest.fixture(autouse=True)
def clear_cache():
    _RESULT_CACHE.clear()
    yield
    _RESULT_CACHE.clear()


def test_cache_hit_on_repeated_upload(tmp_path):
    settings = Settings(enable_result_cache=True, result_cache_max_size=50)
    provider = StubProvider(settings)
    prompts = PromptRegistry(settings.prompts_dir)
    content = _create_pdf_content("Test presentation claim: PostgreSQL supports JSON.")

    res1 = run_presentation_analysis(
        filename="deck.pdf",
        content=content,
        provider=provider,
        prompts=prompts,
        settings=settings,
    )
    res2 = run_presentation_analysis(
        filename="deck.pdf",
        content=content,
        provider=provider,
        prompts=prompts,
        settings=settings,
    )

    assert res1.analysis_id == res2.analysis_id
    assert res1.scores == res2.scores


def test_cache_disabled_bypasses_cache(tmp_path):
    settings = Settings(enable_result_cache=False, result_cache_max_size=50)
    provider = StubProvider(settings)
    prompts = PromptRegistry(settings.prompts_dir)
    content = _create_pdf_content("Test presentation claim: PostgreSQL supports JSON.")

    res1 = run_presentation_analysis(
        filename="deck.pdf",
        content=content,
        provider=provider,
        prompts=prompts,
        settings=settings,
    )
    res2 = run_presentation_analysis(
        filename="deck.pdf",
        content=content,
        provider=provider,
        prompts=prompts,
        settings=settings,
    )

    assert res1.analysis_id != res2.analysis_id


def test_cache_eviction_lru(tmp_path):
    settings = Settings(enable_result_cache=True, result_cache_max_size=2)
    provider = StubProvider(settings)
    prompts = PromptRegistry(settings.prompts_dir)

    c1 = _create_pdf_content("Slide 1 content claim: Accuracy is 95%.")
    c2 = _create_pdf_content("Slide 2 content claim: Latency is 10ms.")
    c3 = _create_pdf_content("Slide 3 content claim: Dataset size 1000.")

    res1_first = run_presentation_analysis(
        filename="c1.pdf", content=c1, provider=provider, prompts=prompts, settings=settings
    )
    res2 = run_presentation_analysis(
        filename="c2.pdf", content=c2, provider=provider, prompts=prompts, settings=settings
    )
    res3 = run_presentation_analysis(
        filename="c3.pdf", content=c3, provider=provider, prompts=prompts, settings=settings
    )

    # c1 should be evicted because maxsize=2 and c2, c3 were inserted afterwards
    res1_second = run_presentation_analysis(
        filename="c1.pdf", content=c1, provider=provider, prompts=prompts, settings=settings
    )

    assert res1_first.analysis_id != res1_second.analysis_id
