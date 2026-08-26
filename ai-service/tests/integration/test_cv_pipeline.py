"""End to end against the stub. No network, no key, no spend."""
from __future__ import annotations

import pytest

from app.pipeline.run import run_cv_extraction


@pytest.mark.asyncio
async def test_pipeline_returns_a_draft(provider, prompts, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.pipeline.extract_text.from_bytes",
        lambda filename, content: "Skills: Python, SQL\nProjects: recommendation system using Pandas",
    )
    result = await run_cv_extraction(
        filename="x.pdf", content=b"", provider=provider, prompts=prompts
    )
    assert result.status == "draft"
    assert result.run_id
    assert result.prompt_version.startswith("cv_extract")


@pytest.mark.asyncio
async def test_invented_skills_are_dropped(provider, prompts, monkeypatch) -> None:
    """The stub returns Pandas/Scikit-learn/XGBoost. If the source text does not contain
    them, postprocess must drop them and warn."""
    monkeypatch.setattr(
        "app.pipeline.extract_text.from_bytes",
        lambda filename, content: "Skills: Python, SQL",
    )
    result = await run_cv_extraction(
        filename="x.pdf", content=b"", provider=provider, prompts=prompts
    )
    names = {s.name for s in result.extraction.skills}
    assert "XGBoost" not in names
    assert any("Dropped" in w for w in result.warnings)
