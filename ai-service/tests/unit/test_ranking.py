"""Tests for taxonomy-gated semantic ranking and fractional scoring."""
from __future__ import annotations

from datetime import date
import pytest

from app.pipeline import ranking
from app.providers.judge_provider import JudgeResponse
from app.schemas.cv import CVSchema, Experience, JobDescription, SkillEvaluation


@pytest.fixture(autouse=True)
def isolate_ranking_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ranking, "get_cached_ranking", lambda candidate, job: None)
    monkeypatch.setattr(ranking, "store_cached_ranking", lambda candidate, job, result: None)


def _cv(skills: list[str]) -> CVSchema:
    return CVSchema(skills=skills)


def _jd(required: list[str], nice_to_have: list[str] | None = None) -> JobDescription:
    return JobDescription(
        title="Data Analyst",
        required_skills=required,
        nice_to_have_skills=nice_to_have or [],
    )


def _judge_response(requirements: list[str], scores: list[float]) -> JudgeResponse:
    return JudgeResponse(
        evaluations=[
            SkillEvaluation(
                requirement=requirement,
                satisfaction_percent=score,
                reasoning="Mocked evidence-bound evaluation.",
                evidence_quote="Explicit skill: " + requirement,
            )
            for requirement, score in zip(requirements, scores, strict=True)
        ],
        provider="test-gemini",
        model="test-model",
    )


def test_taxonomy_filter_only_sends_relevant_requirements_to_judge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], list[str]]] = []

    def fake_judge(requirements: list[str], evidence: list[str]) -> JudgeResponse:
        calls.append((requirements, evidence))
        return _judge_response(requirements, [80.0])

    monkeypatch.setattr(ranking, "query_judge", fake_judge)
    result = ranking.rank(_cv(["SQL"]), _jd(["SQL", "React"]))

    assert calls[0][0] == ["SQL"]
    assert len(result.skill_evaluations) == 2
    assert result.skill_evaluations[0].satisfaction_percent == 80.0
    assert result.skill_evaluations[1].satisfaction_percent == 0.0
    assert result.judge_provider == "test-gemini"
    assert result.judge_model == "test-model"


def test_fractional_required_and_preferred_scores_are_authoritative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ranking,
        "query_judge",
        lambda requirements, evidence: _judge_response(requirements, [80.0, 20.0, 50.0]),
    )

    result = ranking.rank(_cv(["Python", "SQL", "Docker"]), _jd(["Python", "SQL"], ["Docker"]))

    assert result.score == pytest.approx(55.0)
    assert result.breakdown["required_satisfaction_average"] == pytest.approx(0.5)
    assert result.breakdown["nice_to_have_satisfaction_average"] == pytest.approx(0.5)
    assert result.skill_evaluations[0].satisfaction_percent == 80.0
    assert result.skill_evaluations[1].satisfaction_percent == 20.0
    assert result.skill_evaluations[2].satisfaction_percent == 50.0


def test_unknown_requirement_without_candidate_taxonomy_signal_is_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ranking, "query_judge", lambda requirements, evidence: pytest.fail("judge should not run"))

    result = ranking.rank(CVSchema(), _jd(["Unlisted Skill"]))

    # Under the 70/20/10 formula, min_experience_years=None grants the full 10%
    # experience_component automatically regardless of skill match, so a candidate
    # with zero matching skills scores 10.0, not 0.0. Confirmed as intended behavior.
    assert result.score == 10.0
    assert result.skill_evaluations[0].satisfaction_percent == 0.0
    assert result.judge_provider is None


def test_certifications_are_forwarded_as_candidate_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    certification = "ISTQB® Certified CTFL V4 certified."
    requirement = "ISTQB Certified Tester Foundation Level (CTFL)"
    captured: list[str] = []

    def fake_judge(requirements: list[str], evidence: list[str]) -> JudgeResponse:
        captured.extend(evidence)
        return JudgeResponse(
            evaluations=[
                SkillEvaluation(
                    requirement=requirement,
                    satisfaction_percent=95.0,
                    reasoning="The certification explicitly confirms CTFL certification.",
                    evidence_quote="Certification: " + certification,
                )
            ],
            provider="test-gemini",
            model="test-model",
        )

    monkeypatch.setattr(ranking, "query_judge", fake_judge)
    result = ranking.rank(
        CVSchema(certifications=[certification]),
        _jd([requirement]),
    )

    assert captured == [
        "Requirement context: " + requirement
        + "\nCandidate evidence excerpt: Certification: " + certification
    ]
    assert result.skill_evaluations[0].satisfaction_percent == 95.0
    assert result.skill_evaluations[0].evidence_quote == "Certification: " + certification


def test_experience_descriptions_are_forwarded_as_candidate_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requirement = "SQL"
    description = "Wrote SQL queries for reporting, SELECT statements, JOINs, and WHERE filters."
    captured: list[str] = []

    def fake_judge(requirements: list[str], evidence: list[str]) -> JudgeResponse:
        captured.extend(evidence)
        return _judge_response(requirements, [25.0])

    monkeypatch.setattr(ranking, "query_judge", fake_judge)
    ranking.rank(
        CVSchema(experience=[{"job_title": "Data Analyst", "description": description}]),
        _jd([requirement]),
    )

    assert captured == [
        "Requirement context: " + requirement
        + "\nCandidate evidence excerpt: Experience: Data Analyst | " + description
    ]


def test_indirect_database_evidence_reaches_judge_for_sql_requirement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requirement = "SQL"
    description = "Used SQL for SELECT statements, JOIN operations, and WHERE clauses in reporting."
    captured: list[list[str]] = []

    def fake_judge(requirements: list[str], evidence: list[str]) -> JudgeResponse:
        captured.append(evidence)
        return _judge_response(requirements, [35.0])

    monkeypatch.setattr(ranking, "query_judge", fake_judge)
    result = ranking.rank(
        CVSchema(projects=[{"description": description}]),
        _jd([requirement]),
    )

    assert captured == [[
        "Requirement context: " + requirement
        + "\nCandidate evidence excerpt: Project description: " + description
    ]]
    assert result.skill_evaluations[0].satisfaction_percent == 35.0


def test_duplicate_requirements_are_deduplicated_before_judging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    judged_requirements: list[str] = []

    def fake_judge(requirements: list[str], evidence: list[str]) -> JudgeResponse:
        judged_requirements.extend(requirements)
        return _judge_response(requirements, [100.0, 50.0])

    monkeypatch.setattr(ranking, "query_judge", fake_judge)
    result = ranking.rank(_cv(["Python", "SQL"]), _jd(["Python", "python", "SQL"]))

    assert judged_requirements == ["Python", "SQL"]
    assert result.breakdown["required_skills_total"] == 2
    # Required avg 75% (both skills have source_multiplier 1.0, explicit CV skills) × 0.70 = 52.5%,
    # plus min_experience_years=None granting full 10% experience_component = 62.5%.
    assert result.score == pytest.approx(62.5)


def test_paraphrased_requirement_uses_candidate_domain_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_judge(requirements: list[str], evidence: list[str]) -> JudgeResponse:
        calls.append(evidence)
        return _judge_response(requirements, [35.0])

    monkeypatch.setattr(ranking, "query_judge", fake_judge)
    requirement = "Build reliable data transformations for reporting"
    result = ranking.rank(_cv(["SQL"]), _jd([requirement]))

    assert calls == [["Requirement context: " + requirement + "\nCandidate evidence excerpt: Explicit skill: SQL"]]
    assert result.skill_evaluations[0].satisfaction_percent == 35.0
    # Judge satisfaction 35% with source_multiplier 0.5 (paraphrased requirement has no identifiable
    # taxonomy term, conservative narrative default) -> final_skill_score 17.5%.
    # Required component 17.5% × 0.70 = 12.25%, plus 10% experience_component (min_experience_years=None) = 22.25%.
    assert result.score == pytest.approx(22.25)


def test_cached_ranking_is_returned_without_calling_judge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cached = ranking.RankingResult(
        score=42.0,
        judge_provider="cached",
        judge_model="cached-model",
        skill_evaluations=[],
        breakdown={},
    )
    monkeypatch.setattr(ranking, "get_cached_ranking", lambda candidate, job: cached)
    monkeypatch.setattr(ranking, "query_judge", lambda requirements, evidence: pytest.fail("judge should not run"))

    assert ranking.rank(_cv(["Python"]), _jd(["Python"])) is cached


def test_explicit_skill_yields_full_source_multiplier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ranking,
        "query_judge",
        lambda requirements, evidence: _judge_response(requirements, [90.0]),
    )
    result = ranking.rank(_cv(["Python"]), _jd(["Python"]))

    assert len(result.skill_evaluations) == 1
    assert result.skill_evaluations[0].source_multiplier == 1.0
    assert result.skill_evaluations[0].final_skill_score == 90.0


def test_narrative_only_skill_yields_half_source_multiplier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ranking,
        "query_judge",
        lambda requirements, evidence: _judge_response(requirements, [80.0]),
    )
    candidate = CVSchema(
        projects=[{"name": "E-Commerce", "description": "Built services with MySQL backend"}]
    )
    result = ranking.rank(candidate, _jd(["MySQL"]))

    assert len(result.skill_evaluations) == 1
    assert result.skill_evaluations[0].source_multiplier == 0.5
    assert result.skill_evaluations[0].final_skill_score == 40.0


def test_explicit_and_narrative_skill_awards_explicit_multiplier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ranking,
        "query_judge",
        lambda requirements, evidence: _judge_response(requirements, [100.0]),
    )
    candidate = CVSchema(
        skills=["Python"],
        projects=[{"description": "Developed automation with Python"}],
    )
    result = ranking.rank(candidate, _jd(["Python"]))

    assert len(result.skill_evaluations) == 1
    assert result.skill_evaluations[0].source_multiplier == 1.0
    assert result.skill_evaluations[0].final_skill_score == 100.0


def test_unresolvable_narrative_requirement_defaults_conservatively_without_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ranking,
        "query_judge",
        lambda requirements, evidence: _judge_response(requirements, [60.0]),
    )
    candidate = CVSchema(skills=["Python"])
    unresolvable_requirement = "Demonstrate exceptional cross-functional empathy and team leadership"
    result = ranking.rank(candidate, _jd([unresolvable_requirement]))

    assert len(result.skill_evaluations) == 1
    assert result.skill_evaluations[0].source_multiplier == 0.5
    assert result.skill_evaluations[0].final_skill_score == 30.0


def test_final_skill_score_calculation_scales_accurately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ranking,
        "query_judge",
        lambda requirements, evidence: _judge_response(requirements, [80.0]),
    )
    candidate = CVSchema(
        projects=[{"technologies_mentioned": ["Docker"]}]
    )
    result = ranking.rank(candidate, _jd(["Docker"]))

    eval_item = result.skill_evaluations[0]
    assert eval_item.satisfaction_percent == 80.0
    assert eval_item.source_multiplier == 0.5
    assert eval_item.final_skill_score == 40.0


def test_calculate_total_experience_years_single_normal_entry() -> None:
    roles = [Experience(job_title="Software Engineer", start_date="01/2020", end_date="01/2022")]
    years = ranking.calculate_total_experience_years(roles)
    assert years == 2.0


def test_calculate_total_experience_years_ongoing_role_none_end_date() -> None:
    roles = [Experience(job_title="DevOps Engineer", start_date="01/2020", end_date=None)]
    years = ranking.calculate_total_experience_years(roles)
    expected = round((date.today() - date(2020, 1, 1)).days / 365.25, 2)
    assert years == pytest.approx(expected, abs=0.05)


def test_calculate_total_experience_years_ongoing_role_string_indicators() -> None:
    roles_present = [Experience(job_title="Frontend Developer", start_date="01/2020", end_date="Present")]
    roles_current = [Experience(job_title="Frontend Developer", start_date="01/2020", end_date="current")]
    expected = round((date.today() - date(2020, 1, 1)).days / 365.25, 2)
    assert ranking.calculate_total_experience_years(roles_present) == pytest.approx(expected, abs=0.05)
    assert ranking.calculate_total_experience_years(roles_current) == pytest.approx(expected, abs=0.05)


def test_calculate_total_experience_years_missing_or_malformed_start_date_skipped() -> None:
    roles = [
        Experience(job_title="Intern", start_date=None, end_date="01/2022"),
        Experience(job_title="Tester", start_date="invalid-date-string", end_date="01/2022"),
    ]
    years = ranking.calculate_total_experience_years(roles)
    assert years == 0.0


def test_calculate_total_experience_years_multiple_valid_entries_summed() -> None:
    roles = [
        Experience(job_title="Junior Dev", start_date="01/2018", end_date="01/2020"),
        Experience(job_title="Mid Dev", start_date="01/2020", end_date="01/2022"),
    ]
    years = ranking.calculate_total_experience_years(roles)
    assert years == 4.0


def test_calculate_total_experience_years_inverted_dates_produce_zero_contribution() -> None:
    roles = [
        Experience(job_title="Time Traveler", start_date="01/2022", end_date="01/2020"),
    ]
    years = ranking.calculate_total_experience_years(roles)
    assert years == 0.0


def test_calculate_total_experience_years_empty_list_returns_zero() -> None:
    assert ranking.calculate_total_experience_years([]) == 0.0


def test_calculate_total_experience_years_mixed_date_format_variants() -> None:
    roles = [
        Experience(job_title="Role 1", start_date="01/2018", end_date="01/2019"),
        Experience(job_title="Role 2", start_date="January 2019", end_date="Jan 2020"),
        Experience(job_title="Role 3", start_date="2020", end_date="2022"),
        Experience(job_title="Role 4", start_date="2022-01", end_date="2023-01"),
    ]
    years = ranking.calculate_total_experience_years(roles)
    assert years == 5.0


def test_ranking_scoring_formula_min_experience_unset_grants_full_experience_weight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # min_experience_years unset (None) -> experience_component contributes full 0.10 regardless of actual experience
    monkeypatch.setattr(
        ranking,
        "query_judge",
        lambda requirements, evidence: _judge_response(requirements, [100.0]),
    )
    candidate = CVSchema(skills=["Python"], experience=[])
    jd = JobDescription(title="Python Dev", required_skills=["Python"], min_experience_years=None)
    result = ranking.rank(candidate, jd)

    # Required: 100.0 * 1.0 (explicit) * 0.70 = 70.0
    # Nice to have: 0.0
    # Experience: 1.0 * 0.10 = 10.0
    # Total: 70.0 + 10.0 = 80.0
    assert result.score == 80.0


def test_ranking_scoring_formula_min_experience_zero_grants_full_experience_weight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # min_experience_years = 0 -> experience_component contributes full 0.10
    monkeypatch.setattr(
        ranking,
        "query_judge",
        lambda requirements, evidence: _judge_response(requirements, [100.0]),
    )
    candidate = CVSchema(skills=["Python"], experience=[])
    jd = JobDescription(title="Python Dev", required_skills=["Python"], min_experience_years=0)
    result = ranking.rank(candidate, jd)

    # Required: 100.0 * 1.0 * 0.70 = 70.0
    # Nice to have: 0.0
    # Experience: 1.0 * 0.10 = 10.0
    # Total: 70.0 + 10.0 = 80.0
    assert result.score == 80.0


def test_ranking_scoring_formula_candidate_experience_exceeds_min_is_capped_at_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Candidate experience exceeds min_experience_years -> experience_ratio capped at 1.0
    monkeypatch.setattr(
        ranking,
        "query_judge",
        lambda requirements, evidence: _judge_response(requirements, [100.0]),
    )
    candidate = CVSchema(
        skills=["Python"],
        experience=[Experience(job_title="Senior Dev", start_date="01/2018", end_date="01/2023")],
    )
    jd = JobDescription(title="Python Dev", required_skills=["Python"], min_experience_years=3)
    result = ranking.rank(candidate, jd)

    # Required: 100.0 * 1.0 * 0.70 = 70.0
    # Experience: min(5.0 / 3, 1.0) * 0.10 = 10.0
    # Total: 70.0 + 10.0 = 80.0
    assert result.score == 80.0


def test_ranking_scoring_formula_candidate_experience_partial_credit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Candidate experience falls short of min_experience_years -> proportional partial credit
    monkeypatch.setattr(
        ranking,
        "query_judge",
        lambda requirements, evidence: _judge_response(requirements, [100.0]),
    )
    candidate = CVSchema(
        skills=["Python"],
        experience=[Experience(job_title="Mid Dev", start_date="01/2020", end_date="01/2022")],
    )
    jd = JobDescription(title="Python Dev", required_skills=["Python"], min_experience_years=4)
    result = ranking.rank(candidate, jd)

    # Required: 100.0 * 1.0 * 0.70 = 70.0
    # Nice to have: 0.0
    # Experience: (2.0 / 4.0) * 0.10 = 0.5 * 0.10 = 0.05 (5.0%)
    # Total: 70.0 + 5.0 = 75.0
    assert result.score == 75.0


def test_ranking_scoring_formula_full_end_to_end_hand_computed_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # End-to-end 70/20/10 scoring test with explicit vs narrative source multipliers & experience:
    #
    # Candidate:
    # - Explicit skill: "Python" (source_multiplier = 1.0)
    # - Narrative skill in project description: "PostgreSQL" (source_multiplier = 0.5)
    # - Experience: 2.0 years ("01/2020" to "01/2022")
    #
    # Job Description:
    # - Required skills: ["Python", "PostgreSQL"]
    # - Nice to have skills: ["Docker"]
    # - min_experience_years: 4
    #
    # Mocked Judge:
    # - Python satisfaction: 80.0% -> final_skill_score = 80.0 * 1.0 = 80.0
    # - PostgreSQL satisfaction: 60.0% -> final_skill_score = 60.0 * 0.5 = 30.0
    # - Docker: no candidate evidence, skipped -> final_skill_score = 0.0
    #
    # Hand-calculation:
    # 1. Required component (70%):
    #    avg_final_score = (80.0 + 30.0) / 2 = 55.0
    #    required_component = (55.0 / 100.0) * 0.70 = 0.385 (38.5%)
    # 2. Nice-to-have component (20%):
    #    avg_final_score = 0.0
    #    nice_to_have_component = 0.0 * 0.20 = 0.0 (0.0%)
    # 3. Experience component (10%):
    #    experience_ratio = min(2.0 / 4, 1.0) = 0.5
    #    experience_component = 0.5 * 0.10 = 0.05 (5.0%)
    # 4. Final score:
    #    final_score = 0.385 + 0.0 + 0.05 = 0.435 -> round(0.435 * 100, 2) = 43.5
    def fake_judge(requirements: list[str], evidence: list[str]) -> JudgeResponse:
        scores = []
        for req in requirements:
            if req == "Python":
                scores.append(80.0)
            elif req == "PostgreSQL":
                scores.append(60.0)
            else:
                scores.append(0.0)
        return _judge_response(requirements, scores)

    monkeypatch.setattr(ranking, "query_judge", fake_judge)

    candidate = CVSchema(
        skills=["Python"],
        projects=[{"name": "Web App", "description": "Backend database using PostgreSQL"}],
        experience=[Experience(job_title="Dev", start_date="01/2020", end_date="01/2022")],
    )
    jd = JobDescription(
        title="Full Stack Engineer",
        required_skills=["Python", "PostgreSQL"],
        nice_to_have_skills=["Docker"],
        min_experience_years=4,
    )
    result = ranking.rank(candidate, jd)

    assert result.score == pytest.approx(43.5)
    assert result.skill_evaluations[0].final_skill_score == 80.0
    assert result.skill_evaluations[1].final_skill_score == 30.0
    assert result.skill_evaluations[2].final_skill_score == 0.0


def test_ranking_scoring_formula_no_required_skills_computes_from_nice_to_have_and_experience(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No required skills at all in the JD (only nice-to-have) -> required_component is 0.0,
    # and final_score computes from nice_to_have_component + experience_component only.
    monkeypatch.setattr(
        ranking,
        "query_judge",
        lambda requirements, evidence: _judge_response(requirements, [100.0]),
    )
    candidate = CVSchema(
        skills=["Docker"],
        experience=[Experience(job_title="Consultant", start_date="01/2020", end_date="01/2022")],
    )
    jd = JobDescription(
        title="DevOps Consultant",
        required_skills=[],
        nice_to_have_skills=["Docker"],
        min_experience_years=2,
    )
    result = ranking.rank(candidate, jd)

    # Required component: 0.0 * 0.70 = 0.0
    # Nice to have component: 1.0 * 0.20 = 0.20 (20.0%)
    # Experience component: min(2.0 / 2.0, 1.0) * 0.10 = 0.10 (10.0%)
    # Total: 0.0 + 20.0 + 10.0 = 30.0
    assert result.score == 30.0


def test_ranking_breakdown_contains_all_70_20_10_and_legacy_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ranking,
        "query_judge",
        lambda requirements, evidence: _judge_response(requirements, [80.0]),
    )
    candidate = CVSchema(
        skills=["Python"],
        experience=[Experience(job_title="Dev", start_date="01/2020", end_date="01/2023")],
    )
    jd = JobDescription(
        title="Backend Engineer",
        required_skills=["Python"],
        nice_to_have_skills=["SQL"],
        min_experience_years=5,
    )
    result = ranking.rank(candidate, jd)

    # Check 70/20/10 specific breakdown fields
    assert result.breakdown["scoring_version"] == "weighted-70-20-10-v1"
    assert result.breakdown["required_component"] == pytest.approx(0.56)  # 0.80 * 1.0 * 0.70 = 0.56
    assert result.breakdown["nice_to_have_component"] == pytest.approx(0.0)
    assert result.breakdown["candidate_total_years"] == 3.0
    assert result.breakdown["experience_ratio"] == pytest.approx(0.6)
    assert result.breakdown["experience_component"] == pytest.approx(0.06)

    # Check legacy breakdown fields remain present for backward compatibility
    assert "required_skills_total" in result.breakdown
    assert "required_satisfaction_average" in result.breakdown
    assert "nice_to_have_skills_total" in result.breakdown
    assert "nice_to_have_satisfaction_average" in result.breakdown
    assert "preferred_bonus" in result.breakdown
    assert "hard_skill_score" in result.breakdown
    assert "hard_skill_weight" in result.breakdown
    assert "semantic_weight" in result.breakdown
    assert "taxonomy_version" in result.breakdown
    assert "judge_prompt_version" in result.breakdown


def test_ranking_breakdown_candidate_total_years_visible_when_min_experience_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ranking,
        "query_judge",
        lambda requirements, evidence: _judge_response(requirements, [100.0]),
    )
    candidate = CVSchema(
        skills=["Python"],
        experience=[Experience(job_title="Dev", start_date="01/2020", end_date="01/2022")],
    )
    jd = JobDescription(title="Python Dev", required_skills=["Python"], min_experience_years=None)
    result = ranking.rank(candidate, jd)

    assert result.breakdown["candidate_total_years"] == 2.0
    assert result.breakdown["experience_ratio"] == 1.0
    assert result.breakdown["experience_component"] == 0.10


def test_hierarchical_parent_skill_match_awards_0_8_multiplier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Candidate with explicit Machine Learning evaluated against requirement for Linear Regression
    monkeypatch.setattr(
        ranking,
        "query_judge",
        lambda requirements, evidence: _judge_response(requirements, [65.0]),
    )
    candidate = CVSchema(skills=["Machine Learning"])
    jd = JobDescription(
        title="ML Engineer",
        required_skills=["Linear Regression"],
        min_experience_years=0,
    )
    result = ranking.rank(candidate, jd)

    evaluation = result.skill_evaluations[0]
    assert evaluation.requirement == "Linear Regression"
    assert evaluation.satisfaction_percent == 65.0
    assert evaluation.source_multiplier == 0.80
    assert evaluation.final_skill_score == pytest.approx(52.0)  # 65.0 * 0.80
    # Score: 52.0 * 0.70 + 0.10 * 100 = 36.40 + 10.0 = 46.40
    assert result.score == pytest.approx(46.40)


def test_child_skill_does_not_infer_hierarchy_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ranking,
        "query_judge",
        lambda requirements, evidence: pytest.fail("child evidence must not judge parent"),
    )

    result = ranking.rank(_cv(["Selenium"]), _jd(["Automation Testing"]))

    evaluation = result.skill_evaluations[0]
    assert evaluation.satisfaction_percent == 0.0
    assert evaluation.final_skill_score == 0.0


def test_related_children_do_not_infer_integration_testing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ranking,
        "query_judge",
        lambda requirements, evidence: pytest.fail("related children must not infer parent"),
    )

    result = ranking.rank(
        _cv(["API Testing", "Database Testing"]),
        _jd(["Integration Testing"]),
    )

    assert result.skill_evaluations[0].satisfaction_percent == 0.0
    assert result.skill_evaluations[0].final_skill_score == 0.0


def test_explicit_parent_can_still_support_child_with_partial_multiplier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ranking,
        "query_judge",
        lambda requirements, evidence: _judge_response(requirements, [65.0]),
    )

    result = ranking.rank(_cv(["Automation Testing"]), _jd(["Selenium"]))

    evaluation = result.skill_evaluations[0]
    assert evaluation.source_multiplier == 0.80
    assert evaluation.final_skill_score == pytest.approx(52.0)


def test_taxonomy_hierarchy_lookups() -> None:
    from app.skills.canonicalize import (
        get_encompassed_skills_for_ids,
        get_encompassed_subskills,
        get_parent_skills,
        is_parent_of,
    )

    # Direct parent checks
    assert is_parent_of("Machine Learning", "Linear Regression") is True
    assert is_parent_of("Deep Learning", "Convolutional Neural Networks") is True
    assert is_parent_of("Backend Development", "REST APIs") is True
    assert is_parent_of("Frontend Development", "React") is True
    assert is_parent_of("Cloud Computing", "AWS") is True
    assert is_parent_of("Software Testing", "Automation Testing") is True

    # Reverse direction is False
    assert is_parent_of("Linear Regression", "Machine Learning") is False

    # Lookup functions
    ml_subskills = get_encompassed_subskills("skill.machine_learning")
    assert "skill.linear_regression" in ml_subskills
    assert "skill.logistic_regression" in ml_subskills

    lr_parents = get_parent_skills("skill.linear_regression")
    assert "skill.machine_learning" in lr_parents

    encompassed_set = get_encompassed_skills_for_ids({"skill.machine_learning"})
    assert "skill.linear_regression" in encompassed_set
    assert "skill.decision_trees" in encompassed_set


def test_calculate_source_multiplier_all_four_tiers() -> None:
    from app.pipeline.ranking import _calculate_source_multiplier

    explicit_ids = {"skill.python", "skill.machine_learning"}
    parent_skill_ids = {"skill.linear_regression", "skill.logistic_regression"}
    narrative_ids = {"skill.docker"}

    # 1. Direct explicit match -> 1.0
    assert _calculate_source_multiplier("Python", explicit_ids, narrative_ids, parent_skill_ids) == 1.0

    # 2. Hierarchical parent match -> 0.80
    assert _calculate_source_multiplier("Linear Regression", explicit_ids, narrative_ids, parent_skill_ids) == 0.80

    # 3. Narrative match -> 0.50
    assert _calculate_source_multiplier("Docker", explicit_ids, narrative_ids, parent_skill_ids) == 0.50

    # 4. Fallback / Unresolvable -> 0.50
    assert _calculate_source_multiplier("Unknown Requirement", explicit_ids, narrative_ids, parent_skill_ids) == 0.50


def test_vague_mention_remains_capped_at_low_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Candidate with only a project description mentioning generic data evaluated against Index Optimization
    monkeypatch.setattr(
        ranking,
        "query_judge",
        lambda requirements, evidence: _judge_response(requirements, [20.0]),  # 1-49% tier for vague mention
    )
    candidate = CVSchema(
        experience=[Experience(job_title="Intern", description="Worked with data and simple tables", start_date="01/2023", end_date="01/2024")]
    )
    jd = JobDescription(
        title="Database Administrator",
        required_skills=["Database Indexing"],
        min_experience_years=2,
    )
    result = ranking.rank(candidate, jd)

    evaluation = result.skill_evaluations[0]
    assert evaluation.satisfaction_percent <= 25.0
    assert evaluation.source_multiplier == 0.50  # Narrative/fallback
    assert evaluation.final_skill_score <= 12.50


def test_extract_requirement_skill_ids_filters_incidental_parent_substring() -> None:
    from app.pipeline.ranking import _extract_requirement_skill_ids

    # STLC contains "Software Testing", which is a hierarchy parent, but the whole phrase is STLC
    ids = _extract_requirement_skill_ids("Software Testing Life Cycle (STLC)")
    assert "skill.software_testing" not in ids


def test_extract_requirement_skill_ids_allows_exact_parent_match() -> None:
    from app.pipeline.ranking import _extract_requirement_skill_ids

    # Exact parent requirement string resolves directly to the parent skill ID
    ml_ids = _extract_requirement_skill_ids("Machine Learning")
    assert "skill.machine_learning" in ml_ids

    st_ids = _extract_requirement_skill_ids("Software Testing")
    assert "skill.software_testing" in st_ids


def test_stlc_requirement_does_not_get_explicit_multiplier_from_generic_software_testing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Candidate with only generic "Software testing" evaluated against STLC
    monkeypatch.setattr(
        ranking,
        "query_judge",
        lambda requirements, evidence: _judge_response(requirements, [0.0]),
    )
    candidate = CVSchema(skills=["Software testing"])
    jd = JobDescription(
        title="QA Engineer",
        required_skills=["Software Testing Life Cycle (STLC)"],
        min_experience_years=0,
    )
    result = ranking.rank(candidate, jd)

    evaluation = result.skill_evaluations[0]
    # source_multiplier must NOT be 1.0 (should be 0.50 fallback)
    assert evaluation.source_multiplier == 0.50
    assert evaluation.final_skill_score == 0.0


def test_exact_parent_requirement_awards_1_0_explicit_multiplier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Candidate with explicit "Machine Learning" evaluated against exact "Machine Learning"
    monkeypatch.setattr(
        ranking,
        "query_judge",
        lambda requirements, evidence: _judge_response(requirements, [100.0]),
    )
    candidate = CVSchema(skills=["Machine Learning"])
    jd = JobDescription(
        title="ML Engineer",
        required_skills=["Machine Learning"],
        min_experience_years=0,
    )
    result = ranking.rank(candidate, jd)

    evaluation = result.skill_evaluations[0]
    assert evaluation.source_multiplier == 1.0
    assert evaluation.final_skill_score == 100.0


# =============================================================================
# Skill Alternative Groups Tests (Tasks 1-3)
# =============================================================================


def test_required_skill_group_takes_max_not_average(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 4 alternatives in 1 group: 1 member scores 100%, 3 score 0%
    monkeypatch.setattr(
        ranking,
        "query_judge",
        lambda requirements, evidence: _judge_response(
            requirements,
            [100.0 if r == "PostgreSQL" else 0.0 for r in requirements],
        ),
    )
    candidate = CVSchema(skills=["PostgreSQL"])
    jd = JobDescription(
        title="Database Engineer",
        required_skills=[],
        required_skill_groups=[["PostgreSQL", "MySQL", "Oracle", "MongoDB"]],
        min_experience_years=0,
    )
    result = ranking.rank(candidate, jd)

    # 1 group contributes 100% -> required_component = 1.0 * 0.70 = 0.70 (70.0 points)
    # Plus min_experience_years=0 grants full 10% experience_component (10.0 points) -> score = 80.0
    assert result.breakdown["required_skills_total"] == 1
    assert result.breakdown["required_satisfaction_average"] == pytest.approx(1.0)
    assert result.breakdown["required_component"] == pytest.approx(0.70)
    assert result.breakdown["experience_component"] == pytest.approx(0.10)
    assert result.score == pytest.approx(80.0)


def test_required_skill_group_all_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Group where all members score 0.0
    candidate = CVSchema(skills=[])
    jd = JobDescription(
        title="Database Engineer",
        required_skills=["Python"],
        required_skill_groups=[["PostgreSQL", "MySQL"]],
        min_experience_years=0,
    )
    monkeypatch.setattr(
        ranking,
        "query_judge",
        lambda requirements, evidence: _judge_response(requirements, [0.0 for _ in requirements]),
    )
    result = ranking.rank(candidate, jd)

    # Denominator must be 2 (1 required + 1 group), numerator = 0 -> average = 0.0
    # required_component = 0.0, plus 10.0 experience_component -> score = 10.0
    assert result.breakdown["required_skills_total"] == 2
    assert result.breakdown["required_satisfaction_average"] == pytest.approx(0.0)
    assert result.breakdown["required_component"] == pytest.approx(0.0)
    assert result.breakdown["experience_component"] == pytest.approx(0.10)
    assert result.score == pytest.approx(10.0)


def test_required_skill_group_multiple_matches_takes_max(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Candidate with both React (80%) and Vue (60%) in an alternative group
    score_map = {"React": 80.0, "Vue": 60.0, "Angular": 0.0}
    monkeypatch.setattr(
        ranking,
        "query_judge",
        lambda requirements, evidence: _judge_response(
            requirements,
            [score_map.get(r, 0.0) for r in requirements],
        ),
    )
    candidate = CVSchema(skills=["React", "Vue"])
    jd = JobDescription(
        title="Frontend Engineer",
        required_skills=[],
        required_skill_groups=[["React", "Vue", "Angular"]],
        min_experience_years=0,
    )
    result = ranking.rank(candidate, jd)

    # Max score is React (80.0 * 1.0 multiplier = 80.0). Average must be 0.80.
    assert result.breakdown["required_satisfaction_average"] == pytest.approx(0.80)
    assert result.breakdown["required_component"] == pytest.approx(0.56)

    rep_evals = [e for e in result.skill_evaluations if e.is_group_representative]
    assert len(rep_evals) == 1
    assert rep_evals[0].requirement == "React"
    assert rep_evals[0].final_skill_score == 80.0


def test_skill_evaluations_shows_all_group_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    score_map = {"FastAPI": 90.0, "Flask": 50.0, "Django": 30.0}
    monkeypatch.setattr(
        ranking,
        "query_judge",
        lambda requirements, evidence: _judge_response(
            requirements,
            [score_map.get(r, 0.0) for r in requirements],
        ),
    )
    candidate = CVSchema(skills=["FastAPI", "Flask", "Django"])
    jd = JobDescription(
        title="Python Engineer",
        required_skills=["Python"],
        required_skill_groups=[["FastAPI", "Flask", "Django"]],
        min_experience_years=0,
    )
    result = ranking.rank(candidate, jd)

    # All 4 evaluations must be present: 1 required + 3 group members
    assert len(result.skill_evaluations) == 4
    group_evals = [e for e in result.skill_evaluations if e.skill_group_id == 0]
    assert len(group_evals) == 3

    # Every member of group 0 has skill_group_id == 0
    for e in group_evals:
        assert e.skill_group_id == 0

    # Only FastAPI (max score 90.0) is marked representative
    fastapi_eval = next(e for e in group_evals if e.requirement == "FastAPI")
    flask_eval = next(e for e in group_evals if e.requirement == "Flask")
    django_eval = next(e for e in group_evals if e.requirement == "Django")

    assert fastapi_eval.is_group_representative is True
    assert flask_eval.is_group_representative is False
    assert django_eval.is_group_representative is False


def test_required_skills_total_counts_group_as_one() -> None:
    jd = JobDescription(
        title="Fullstack Engineer",
        required_skills=["TypeScript", "Git"],
        required_skill_groups=[
            ["React", "Vue", "Angular"],
            ["PostgreSQL", "MySQL"],
        ],
    )
    candidate = CVSchema()
    result = ranking.rank(candidate, jd)

    # 2 independent required + 2 groups = 4 total
    assert result.breakdown["required_skills_total"] == 4
    assert len(result.skill_evaluations) == 7  # 2 + 3 + 2 = 7 detailed evaluations


def test_no_groups_identical_to_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression test: ungrouped JD produces exact identical breakdown and scores
    monkeypatch.setattr(
        ranking,
        "query_judge",
        lambda requirements, evidence: _judge_response(requirements, [80.0, 20.0, 50.0]),
    )
    candidate = CVSchema(skills=["Python", "SQL", "Docker"])
    jd = JobDescription(
        title="Data Analyst",
        required_skills=["Python", "SQL"],
        nice_to_have_skills=["Docker"],
        min_experience_years=None,
    )
    result = ranking.rank(candidate, jd)

    expected_breakdown = {
        "required_skills_total": 2,
        "required_satisfaction_average": 0.5,
        "nice_to_have_skills_total": 1,
        "nice_to_have_satisfaction_average": 0.5,
        "preferred_bonus": 0.05,
        "hard_skill_score": 0.55,
        "hard_skill_weight": 1.0,
        "semantic_weight": 0.0,
        "taxonomy_version": "2026.09",
        "judge_prompt_version": "ranking-judge-v1",
        "scoring_version": "weighted-70-20-10-v1",
        "fallback_to_taxonomy": False,
        "required_component": 0.35,
        "nice_to_have_component": 0.1,
        "experience_component": 0.1,
        "candidate_total_years": 0.0,
        "experience_ratio": 1.0,
    }
    assert result.score == 55.0
    assert result.breakdown == expected_breakdown
    for evaluation in result.skill_evaluations:
        assert evaluation.skill_group_id is None
        assert evaluation.is_group_representative is False


def test_validation_error_skill_in_both_required_and_group() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc_info:
        JobDescription(
            title="Backend Engineer",
            required_skills=["Python"],
            required_skill_groups=[["python", "Go"]],
        )

    assert "Python" in str(exc_info.value) or "python" in str(exc_info.value)
    assert "cannot be listed as both an independent requirement and part of an alternative group" in str(exc_info.value)


def test_validation_error_single_member_group() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc_info:
        JobDescription(
            title="Backend Engineer",
            required_skills=["Python"],
            required_skill_groups=[["Go"]],
        )

    assert "must contain at least 2 skills" in str(exc_info.value)


def test_job_description_normalize_legacy_payload_dictionary_and_job_title() -> None:
    # 1. Non-dict input handled safely
    assert JobDescription.normalize_legacy_payload("not-a-dict") == "not-a-dict"

    # 2. Legacy job_title and nested dictionary required_skills + preferred_qualifications
    legacy_payload = {
        "job_title": "Senior Engineer",
        "required_skills": {
            "languages": ["Python", "Rust"],
            "databases": ["PostgreSQL"],
        },
        "preferred_qualifications": ["Docker", "K8s"],
    }
    jd = JobDescription(**legacy_payload)
    assert jd.title == "Senior Engineer"
    assert set(jd.required_skills) == {"Python", "Rust", "PostgreSQL"}
    assert jd.nice_to_have_skills == ["Docker", "K8s"]







