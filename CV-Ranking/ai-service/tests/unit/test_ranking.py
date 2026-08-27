"""rank() must stay deterministic: no LLM call, and semantic_fit is the only
non-pure input — so every test here pins it with monkeypatch instead of
loading the real embeddings model (no network in CI, per eval/README.md).
"""
from __future__ import annotations

import pytest

from app.pipeline import ranking
from app.schemas.cv import CVSchema, JobDescription


def _cv(skills: list[str]) -> CVSchema:
    return CVSchema(skills=skills)


def _jd(required: list[str], nice_to_have: list[str] | None = None) -> JobDescription:
    return JobDescription(
        title="Data Analyst",
        required_skills=required,
        nice_to_have_skills=nice_to_have or [],
    )


def test_full_match_scores_highest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ranking, "semantic_fit", lambda cv, jd: 1.0)

    candidate = _cv(["Python", "SQL", "Pandas"])
    jd = _jd(required=["Python", "SQL", "Pandas"])

    result = ranking.rank(candidate, jd)

    assert result.matched_skills == ["Python", "SQL", "Pandas"]
    assert result.missing_skills == []
    assert result.score == 100.0
    assert result.breakdown["required_match_ratio"] == 1.0


def test_missing_required_skill_lowers_score_and_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ranking, "semantic_fit", lambda cv, jd: 0.0)

    candidate = _cv(["Python", "SQL"])
    jd = _jd(required=["Python", "SQL", "Tableau"])

    result = ranking.rank(candidate, jd)

    assert result.matched_skills == ["Python", "SQL"]
    assert result.missing_skills == ["Tableau"]
    assert 0.0 < result.score < 100.0
    assert result.breakdown["required_skills_matched"] == 2
    assert result.breakdown["required_skills_total"] == 3


def test_skill_unknown_to_taxonomy_falls_back_to_exact_text_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ranking, "semantic_fit", lambda cv, jd: 0.0)

    # "Underwater Basket Weaving" isn't in taxonomy.yaml, so canonicalise()
    # returns None for it (see tests/unit/test_canonicalize.py). Same exact
    # text on both sides must still count as matched via the raw-text
    # fallback in app/pipeline/ranking.py — an unknown skill shouldn't be
    # punished just because the taxonomy hasn't caught up to it yet.
    candidate = _cv(["Python", "Underwater Basket Weaving"])
    jd = _jd(required=["Python", "Underwater Basket Weaving"])

    result = ranking.rank(candidate, jd)

    assert result.matched_skills == ["Python", "Underwater Basket Weaving"]
    assert result.missing_skills == []


def test_skill_unknown_to_taxonomy_and_absent_from_cv_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ranking, "semantic_fit", lambda cv, jd: 0.0)

    candidate = _cv(["Python"])
    jd = _jd(required=["Python", "Underwater Basket Weaving"])

    result = ranking.rank(candidate, jd)

    assert result.matched_skills == ["Python"]
    assert result.missing_skills == ["Underwater Basket Weaving"]


def test_semantic_fit_is_isolated_from_hard_skill_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same skill overlap, different semantic_fit -> different final score,
    but identical matched/missing skills (semantic_fit never touches those)."""
    monkeypatch.setattr(ranking, "semantic_fit", lambda cv, jd: 0.0)
    candidate = _cv(["Python"])
    jd = _jd(required=["Python"])
    low = ranking.rank(candidate, jd)

    monkeypatch.setattr(ranking, "semantic_fit", lambda cv, jd: 1.0)
    high = ranking.rank(candidate, jd)

    assert low.matched_skills == high.matched_skills == ["Python"]
    assert low.missing_skills == high.missing_skills == []
    assert high.score > low.score


def test_no_required_skills_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ranking, "semantic_fit", lambda cv, jd: 0.5)

    candidate = _cv(["Python"])
    jd = _jd(required=[], nice_to_have=["Docker"])

    result = ranking.rank(candidate, jd)

    assert result.matched_skills == []
    assert result.missing_skills == []
    assert result.breakdown["required_match_ratio"] is None
    