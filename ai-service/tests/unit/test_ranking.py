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


def test_raw_matching_is_bidirectional_for_non_taxonomy_terms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ranking, "semantic_fit", lambda cv, jd: 0.0)

    result = ranking.rank(_cv(["GeminiX"]), _jd(["Google GeminiX"]))

    assert result.matched_skills == ["Google GeminiX"]


def test_reverse_raw_matching_rejects_short_ambiguous_terms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ranking, "semantic_fit", lambda cv, jd: 0.0)

    result = ranking.rank(_cv(["R"]), _jd(["HR Analytics"]))

    assert result.matched_skills == []


def test_semantic_fit_is_reported_without_changing_deterministic_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Semantic context must not change the authoritative hard-skill score."""
    monkeypatch.setattr(ranking, "semantic_fit", lambda cv, jd: 0.0)
    candidate = _cv(["Python"])
    jd = _jd(required=["Python"])
    low = ranking.rank(candidate, jd)

    monkeypatch.setattr(ranking, "semantic_fit", lambda cv, jd: 1.0)
    high = ranking.rank(candidate, jd)

    assert low.matched_skills == high.matched_skills == ["Python"]
    assert low.missing_skills == high.missing_skills == []
    assert high.score == low.score == 100.0
    assert low.semantic_fit == 0.0
    assert high.semantic_fit == 0.0


def test_preferred_only_candidate_has_positive_score_and_visible_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ranking, "semantic_fit", lambda cv, jd: 0.0)

    result = ranking.rank(_cv(["Docker"]), _jd(["Python"], ["Docker"]))

    assert result.score == 20.0
    assert result.matched_required_skills == []
    assert result.matched_preferred_skills == ["Docker"]


def test_duplicate_candidate_skills_do_not_inflate_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ranking, "semantic_fit", lambda cv, jd: 0.0)

    result = ranking.rank(_cv(["Python", "python", "Python"]), _jd(["Python"]))

    assert result.score == 100.0


def test_duplicate_job_skills_do_not_inflate_or_change_the_ratio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ranking, "semantic_fit", lambda cv, jd: 0.0)

    result = ranking.rank(_cv(["Python"]), _jd(["Python", "python", "SQL"]))

    assert result.score == 50.0
    assert result.breakdown["required_skills_total"] == 2


def test_preferred_only_cannot_equal_full_required_match_when_required_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ranking, "semantic_fit", lambda cv, jd: 0.0)

    preferred_only = ranking.rank(_cv(["Docker"]), _jd(["Python"], ["Docker"]))
    full_required = ranking.rank(_cv(["Python"]), _jd(["Python"], ["Docker"]))

    assert preferred_only.score == 20.0
    assert full_required.score == 100.0
    assert preferred_only.score < full_required.score


def test_preferred_only_with_empty_required_list_is_capped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ranking, "semantic_fit", lambda cv, jd: 0.0)

    result = ranking.rank(_cv(["Docker"]), _jd([], ["Docker"]))

    assert result.score == 20.0


def test_no_required_skills_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ranking, "semantic_fit", lambda cv, jd: 0.5)

    candidate = _cv(["Python"])
    jd = _jd(required=[], nice_to_have=["Docker"])

    result = ranking.rank(candidate, jd)

    assert result.matched_skills == []
    assert result.missing_skills == []
    assert result.breakdown["required_match_ratio"] is None


def test_partial_required_match_is_proportional_with_preferred_bonus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ranking, "semantic_fit", lambda cv, jd: 0.0)

    result = ranking.rank(
        _cv(["Python", "Docker"]),
        _jd(["Python", "SQL", "Kubernetes"], ["Docker", "AWS"]),
    )

    assert result.breakdown["required_match_ratio"] == pytest.approx(1 / 3)
    assert result.breakdown["nice_to_have_match_ratio"] == pytest.approx(1 / 2)
    assert result.score == pytest.approx(40.0)


def test_full_required_match_is_100_with_or_without_preferred_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ranking, "semantic_fit", lambda cv, jd: 0.0)

    without_preferred = ranking.rank(_cv(["Python", "SQL"]), _jd(["Python", "SQL"]))
    with_preferred = ranking.rank(
        _cv(["Python", "SQL"]), _jd(["Python", "SQL"], ["Docker"])
    )

    assert without_preferred.score == with_preferred.score == 100.0


def test_preferred_only_is_positive_but_below_full_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ranking, "semantic_fit", lambda cv, jd: 0.0)

    preferred_only = ranking.rank(_cv(["Docker", "AWS"]), _jd(["Python"], ["Docker", "AWS"]))
    full_required = ranking.rank(_cv(["Python"]), _jd(["Python"], ["Docker", "AWS"]))

    assert preferred_only.score == 20.0
    assert preferred_only.score < full_required.score == 100.0


def test_score_is_bounded_and_no_match_is_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ranking, "semantic_fit", lambda cv, jd: 0.0)

    result = ranking.rank(_cv(["Rust"]), _jd(["Python"], ["Docker"]))

    assert result.score == 0.0
    assert 0.0 <= result.score <= 100.0


def test_embedding_provider_cannot_change_authoritative_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(cv: CVSchema, jd: JobDescription) -> float:
        raise AssertionError("semantic provider must not be called")

    monkeypatch.setattr(ranking, "semantic_fit", unavailable)

    result = ranking.rank(_cv(["Python"]), _jd(["Python"]))

    assert result.score == 100.0
    assert result.semantic_fit == 0.0


def test_tc001_grouped_job_description_is_normalized() -> None:
    job_description = JobDescription(
        job_title="AI Instructor",
        required_skills={
            "assistants": ["ChatGPT", "Google Gemini"],
            "generation": ["Runway ML"],
        },
        preferred_qualifications=["Strong portfolio"],
    )

    assert job_description.title == "AI Instructor"
    assert job_description.required_skills == ["ChatGPT", "Google Gemini", "Runway ML"]
    assert job_description.nice_to_have_skills == ["Strong portfolio"]
    