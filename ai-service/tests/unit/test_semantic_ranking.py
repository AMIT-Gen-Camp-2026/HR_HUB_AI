import json
import pytest

from app.pipeline import ranking
from app.pipeline.jd_enrichment import JDEnrichmentError, clear_jd_enrichment_cache
from app.pipeline.run import _ranking_cache, _snapshot_cache
from app.providers.judge_provider import JudgeProviderError, JudgeResponse
from app.schemas.cv import (
    CVSchema,
    Experience,
    JobDescription,
    Project,
    SkillEvaluation,
)


def mock_jd_enrichment_query_model(system_prompt, user_prompt, validate_fn=None, metadata=None):
    """Deterministic mock for JD enrichment LLM calls without live network requests."""
    start_marker = "<<<JDDATA_PAYLOAD_START>>>\n"
    end_marker = "\n<<<JDDATA_PAYLOAD_END>>>"
    if start_marker in user_prompt and end_marker in user_prompt:
        payload_json = user_prompt.split(start_marker)[1].split(end_marker)[0]
        reqs = json.loads(payload_json)
    else:
        reqs = ["Skill"]
    items = [
        {
            "raw_text": req,
            "core_intent": f"Intent for {req}",
            "implied_components": [req],
            "is_composite": False,
            "specificity": "specific",
        }
        for req in reqs
    ]
    raw_json = json.dumps({"requirements": items})
    return validate_fn(raw_json) if validate_fn else raw_json


@pytest.fixture(autouse=True)
def isolate_caches(monkeypatch: pytest.MonkeyPatch):
    _snapshot_cache.clear()
    _ranking_cache.clear()
    clear_jd_enrichment_cache()
    monkeypatch.setattr(ranking, "get_cached_ranking", lambda candidate, job: None)
    monkeypatch.setattr(ranking, "store_cached_ranking", lambda candidate, job, result: None)
    monkeypatch.setattr("app.pipeline.jd_enrichment.query_model", mock_jd_enrichment_query_model)
    yield
    _snapshot_cache.clear()
    _ranking_cache.clear()
    clear_jd_enrichment_cache()


def test_matching_mode_taxonomy_explicit_matches_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit matching_mode='taxonomy' produces identical output to unset (default)."""
    def mock_query_judge(requirements: list[str], evidence: list[str]) -> JudgeResponse:
        return JudgeResponse(
            evaluations=[
                SkillEvaluation(
                    requirement=req,
                    satisfaction_percent=100.0,
                    reasoning="Strong match",
                    evidence_quote="Explicit skill: " + req,
                )
                for req in requirements
            ],
            provider="mock-gemini",
            model="gemini-3.6-flash",
        )

    monkeypatch.setattr(ranking, "query_judge", mock_query_judge)

    cv = CVSchema(
        skills=["Python", "SQL"],
        experience=[
            Experience(
                job_title="Software Engineer",
                company="Acme Corp",
                start_date="2020-01-01",
                end_date="2023-01-01",
            )
        ],
    )

    jd_unset = JobDescription(
        title="Python Developer",
        required_skills=["Python", "SQL"],
        nice_to_have_skills=["Docker"],
        min_experience_years=2,
    )

    jd_explicit = JobDescription(
        title="Python Developer",
        required_skills=["Python", "SQL"],
        nice_to_have_skills=["Docker"],
        min_experience_years=2,
        matching_mode="taxonomy",
    )

    res_unset = ranking.rank(cv, jd_unset)
    res_explicit = ranking.rank(cv, jd_explicit)

    assert res_unset.score == res_explicit.score
    assert res_unset.breakdown == res_explicit.breakdown
    assert res_unset.breakdown["fallback_to_taxonomy"] is False
    assert res_explicit.breakdown["fallback_to_taxonomy"] is False
    assert len(res_unset.skill_evaluations) == len(res_explicit.skill_evaluations)


def test_semantic_mode_end_to_end_with_mocked_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    """Semantic mode end-to-end: satisfaction scores flow into 70/20/10, source_multiplier is 1.0."""
    def mock_query_semantic_judge(requirements, evidence) -> JudgeResponse:
        evals = []
        for req in requirements:
            if req.raw_text == "Python":
                score = 100.0
            elif req.raw_text == "SQL":
                score = 50.0
            elif req.raw_text == "Docker":
                score = 75.0
            else:
                score = 0.0
            evals.append(
                SkillEvaluation(
                    requirement=req.raw_text,
                    satisfaction_percent=score,
                    reasoning=f"Semantic reasoning for {req.raw_text}",
                    evidence_quote=f"Evidence for {req.raw_text}",
                )
            )
        return JudgeResponse(evaluations=evals, provider="mock-semantic", model="test-model")

    monkeypatch.setattr(ranking, "query_semantic_judge", mock_query_semantic_judge)

    cv = CVSchema(
        skills=["Python", "SQL"],
        experience=[
            Experience(
                job_title="Software Developer",
                company="Corp",
                start_date="2020-01-01",
                end_date="2023-01-01",  # ~3.0 years
            )
        ],
    )

    jd = JobDescription(
        title="Backend Engineer",
        required_skills=["Python", "SQL"],
        nice_to_have_skills=["Docker"],
        min_experience_years=3,
        matching_mode="semantic",
    )

    res = ranking.rank(cv, jd)

    # All evaluations in semantic mode must have source_multiplier = 1.0 unconditionally
    assert all(e.source_multiplier == 1.0 for e in res.skill_evaluations)
    for e in res.skill_evaluations:
        assert e.final_skill_score == e.satisfaction_percent

    # Required average: (100.0 + 50.0) / 2 = 75.0% -> required_component = 0.75 * 0.70 = 0.525
    # Preferred average: 75.0% -> nice_to_have_component = 0.75 * 0.20 = 0.150
    # Experience ratio: 3.0 / 3.0 = 1.0 -> experience_component = 1.0 * 0.10 = 0.100
    # Total score = (0.525 + 0.150 + 0.100) * 100 = 77.5
    assert res.score == pytest.approx(77.5, abs=0.5)
    assert res.breakdown["fallback_to_taxonomy"] is False
    assert res.breakdown["judge_prompt_version"] == "semantic-judge-v1"


def test_semantic_mode_with_or_skill_groups(monkeypatch: pytest.MonkeyPatch) -> None:
    """Semantic mode with OR skill groups: highest-member-wins logic applies correctly."""
    def mock_query_semantic_judge(requirements, evidence) -> JudgeResponse:
        evals = []
        for req in requirements:
            if req.raw_text == "PostgreSQL":
                score = 100.0
            elif req.raw_text == "MySQL":
                score = 25.0
            elif req.raw_text == "Python":
                score = 100.0
            else:
                score = 0.0
            evals.append(
                SkillEvaluation(
                    requirement=req.raw_text,
                    satisfaction_percent=score,
                    reasoning=f"Evaluated {req.raw_text}",
                    evidence_quote=f"Quote {req.raw_text}",
                )
            )
        return JudgeResponse(evaluations=evals, provider="mock-semantic", model="test-model")

    monkeypatch.setattr(ranking, "query_semantic_judge", mock_query_semantic_judge)

    cv = CVSchema(skills=["Python", "PostgreSQL"])
    jd = JobDescription(
        title="Database Dev",
        required_skills=["Python"],
        required_skill_groups=[["PostgreSQL", "MySQL"]],
        nice_to_have_skills=[],
        matching_mode="semantic",
    )

    res = ranking.rank(cv, jd)

    # 3 total evaluations: 1 required + 2 group members
    assert len(res.skill_evaluations) == 3
    group_members = [e for e in res.skill_evaluations if e.skill_group_id == 0]
    assert len(group_members) == 2

    # Highest member wins: PostgreSQL (100.0) is representative, MySQL (25.0) is not
    pg_eval = next(e for e in group_members if e.requirement == "PostgreSQL")
    mysql_eval = next(e for e in group_members if e.requirement == "MySQL")
    assert pg_eval.is_group_representative is True
    assert mysql_eval.is_group_representative is False

    # Effective required average: (100 [Python] + 100 [PostgreSQL representative]) / 2 = 100.0
    # Required component: 1.0 * 0.70 = 0.70; Experience (no min): 1.0 * 0.10 = 0.10 -> Score: 80.0
    assert res.score == pytest.approx(80.0)


def test_fallback_when_jd_enrichment_raises_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """When extract_jd_requirements raises JDEnrichmentError, ranking falls back to taxonomy mode."""
    def mock_extract_jd_fail(jd):
        raise JDEnrichmentError("LLM rate limit / timeout on JD enrichment")

    def mock_query_judge(requirements, evidence):
        return JudgeResponse(
            evaluations=[
                SkillEvaluation(
                    requirement=req,
                    satisfaction_percent=80.0,
                    reasoning="Taxonomy fallback evaluation",
                    evidence_quote="Explicit skill: " + req,
                )
                for req in requirements
            ],
            provider="mock-taxonomy",
            model="gemini-3.6-flash",
        )

    monkeypatch.setattr("app.pipeline.ranking.extract_jd_requirements", mock_extract_jd_fail)
    monkeypatch.setattr(ranking, "query_judge", mock_query_judge)

    cv = CVSchema(skills=["Python"])
    jd = JobDescription(
        title="Developer",
        required_skills=["Python"],
        matching_mode="semantic",
    )

    res = ranking.rank(cv, jd)

    assert res.score > 0.0
    assert res.breakdown["fallback_to_taxonomy"] is True


def test_fallback_when_semantic_judge_raises_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """When query_semantic_judge raises JudgeProviderError, ranking falls back to taxonomy mode."""
    def mock_query_semantic_judge_fail(requirements, evidence):
        raise JudgeProviderError("Semantic judge HTTP 503 across full provider chain")

    def mock_query_judge(requirements, evidence):
        return JudgeResponse(
            evaluations=[
                SkillEvaluation(
                    requirement=req,
                    satisfaction_percent=90.0,
                    reasoning="Taxonomy fallback evaluation",
                    evidence_quote="Explicit skill: " + req,
                )
                for req in requirements
            ],
            provider="mock-taxonomy",
            model="gemini-3.6-flash",
        )

    monkeypatch.setattr(ranking, "query_semantic_judge", mock_query_semantic_judge_fail)
    monkeypatch.setattr(ranking, "query_judge", mock_query_judge)

    cv = CVSchema(skills=["Python", "SQL"])
    jd = JobDescription(
        title="Developer",
        required_skills=["Python", "SQL"],
        matching_mode="semantic",
    )

    res = ranking.rank(cv, jd)

    assert res.score > 0.0
    assert res.breakdown["fallback_to_taxonomy"] is True


def test_semantic_mode_reproducibility_10_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Running semantic ranking 10 times with deterministic judge yields byte-identical result payloads."""
    def mock_query_semantic_judge(requirements, evidence) -> JudgeResponse:
        evals = [
            SkillEvaluation(
                requirement=req.raw_text,
                satisfaction_percent=100.0 if "Python" in req.raw_text else 50.0,
                reasoning=f"Reasoning for {req.raw_text}",
                evidence_quote=f"Quote for {req.raw_text}",
            )
            for req in requirements
        ]
        return JudgeResponse(evaluations=evals, provider="mock-semantic", model="test-model")

    monkeypatch.setattr(ranking, "query_semantic_judge", mock_query_semantic_judge)

    cv = CVSchema(
        skills=["Python", "PostgreSQL"],
        experience=[
            Experience(
                job_title="Software Developer",
                company="Corp",
                start_date="2020-01-01",
                end_date="2023-01-01",
            )
        ],
    )

    jd = JobDescription(
        title="Developer",
        required_skills=["Python"],
        required_skill_groups=[["PostgreSQL", "MySQL"]],
        nice_to_have_skills=["Docker"],
        min_experience_years=2,
        matching_mode="semantic",
    )

    first_result = ranking.rank(cv, jd).model_dump()

    for _ in range(9):
        current_result = ranking.rank(cv, jd).model_dump()
        assert current_result == first_result


def test_semantic_mode_invalid_skill_groups_raises_validation_error() -> None:
    """Combining matching_mode='semantic' with invalid skill groups raises ValidationError immediately."""
    from pydantic import ValidationError

    # Single-member group must fail schema validation before ranking starts
    with pytest.raises(ValidationError) as exc_info:
        JobDescription(
            title="Backend Engineer",
            required_skills=["Python"],
            required_skill_groups=[["Go"]],
            matching_mode="semantic",
        )
    assert "must contain at least 2 skills" in str(exc_info.value)

    # Skill listed as both independent required and in alternative group must fail
    with pytest.raises(ValidationError) as exc_info:
        JobDescription(
            title="Backend Engineer",
            required_skills=["Python"],
            required_skill_groups=[["python", "Go"]],
            matching_mode="semantic",
        )
    assert "cannot be listed as both an independent requirement and part of an alternative group" in str(exc_info.value)


def test_invalid_matching_mode_raises_validation_error() -> None:
    """Invalid matching_mode string (e.g. 'fuzzy') must be rejected by Pydantic with ValidationError, not fallback."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc_info:
        JobDescription(
            title="Data Scientist",
            required_skills=["Python"],
            matching_mode="fuzzy",  # type: ignore[arg-type]
        )
    assert "matching_mode" in str(exc_info.value)


def test_ranking_cache_isolation_between_taxonomy_and_semantic(monkeypatch: pytest.MonkeyPatch) -> None:
    """A cached ranking result for taxonomy mode must NEVER be served to a semantic request (and vice versa)."""
    # Enable live caching for this test (override isolate_caches fixture)
    from app.pipeline.run import get_cached_ranking, store_cached_ranking, _ranking_cache
    _ranking_cache.clear()
    monkeypatch.setattr(ranking, "get_cached_ranking", get_cached_ranking)
    monkeypatch.setattr(ranking, "store_cached_ranking", store_cached_ranking)

    def mock_query_judge(requirements: list[str], evidence: list[str]) -> JudgeResponse:
        return JudgeResponse(
            evaluations=[
                SkillEvaluation(
                    requirement=req,
                    satisfaction_percent=100.0,
                    reasoning="Taxonomy judge evaluation",
                    evidence_quote="Explicit skill: " + req,
                )
                for req in requirements
            ],
            provider="mock-taxonomy-judge",
            model="tax-model-1",
        )

    def mock_query_semantic_judge(requirements, evidence) -> JudgeResponse:
        return JudgeResponse(
            evaluations=[
                SkillEvaluation(
                    requirement=req.raw_text,
                    satisfaction_percent=75.0,
                    reasoning="Semantic judge evaluation",
                    evidence_quote="Explicit skill: " + req.raw_text,
                )
                for req in requirements
            ],
            provider="mock-semantic-judge",
            model="sem-model-1",
        )

    monkeypatch.setattr(ranking, "query_judge", mock_query_judge)
    monkeypatch.setattr(ranking, "query_semantic_judge", mock_query_semantic_judge)

    cv = CVSchema(skills=["Python", "SQL"])
    jd_tax = JobDescription(
        title="Developer",
        required_skills=["Python", "SQL"],
        matching_mode="taxonomy",
    )
    jd_sem = JobDescription(
        title="Developer",
        required_skills=["Python", "SQL"],
        matching_mode="semantic",
    )

    # 1. Run taxonomy mode -> populates cache under taxonomy key
    res_tax = ranking.rank(cv, jd_tax)
    assert res_tax.judge_provider == "mock-taxonomy-judge"
    assert res_tax.breakdown["judge_prompt_version"] == "ranking-judge-v1"

    # 2. Run semantic mode -> must NOT reuse taxonomy cache entry
    res_sem = ranking.rank(cv, jd_sem)
    assert res_sem.judge_provider == "mock-semantic-judge"
    assert res_sem.breakdown["judge_prompt_version"] == "semantic-judge-v1"

    # 3. Subsequent calls retrieve from respective cache entries without crossover
    res_tax_cached = ranking.rank(cv, jd_tax)
    assert res_tax_cached.judge_provider == "mock-taxonomy-judge"
    assert res_tax_cached.breakdown["judge_prompt_version"] == "ranking-judge-v1"

    res_sem_cached = ranking.rank(cv, jd_sem)
    assert res_sem_cached.judge_provider == "mock-semantic-judge"
    assert res_sem_cached.breakdown["judge_prompt_version"] == "semantic-judge-v1"

