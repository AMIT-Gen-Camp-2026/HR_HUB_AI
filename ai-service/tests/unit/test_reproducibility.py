"""Tests for scoring reproducibility, taxonomy hierarchy resolution, and judge robustness."""

import pytest
from app.pipeline.ranking import rank, _candidate_taxonomy_id_sets, _calculate_source_multiplier, _extract_requirement_skill_ids, _evidence_for_requirement, _candidate_evidence, _taxonomy_ids
from app.pipeline.run import ranking_cache_key, _snapshot_cache, _ranking_cache
from app.prompts.registry import build_prompt, build_judge_prompt
from app.providers.judge_provider import JudgeProvider, JudgeResponse, SkillEvaluation
from app.schemas.cv import CVSchema, Experience, JobDescription, Project


@pytest.fixture(autouse=True)
def clear_caches() -> None:
    _snapshot_cache.clear()
    _ranking_cache.clear()


def test_parent_requirement_recognizes_child_skills() -> None:
    """Parent skill in candidate (Automation Testing) covers child requirement (Selenium) with 0.80 multiplier and matched evidence."""
    cv = CVSchema(
        skills=["Automation Testing", "Manual Testing"],
        experience=[
            Experience(
                job_title="QA Engineer",
                company="TechCorp",
                start_date="2021-01-01",
                end_date="2023-01-01",
                description="Executed test cases and automated regression suites.",
            )
        ],
    )
    explicit_ids, narrative_ids, parent_skill_ids = _candidate_taxonomy_id_sets(cv)
    req_ids = _extract_requirement_skill_ids("Selenium")
    
    assert "skill.selenium" in req_ids
    
    mult = _calculate_source_multiplier(
        "Selenium",
        explicit_ids,
        narrative_ids,
        parent_skill_ids,
        req_ids,
    )
    assert mult == 0.80

    ev = _candidate_evidence(cv)
    ev_map = {item: _taxonomy_ids(item) for item in ev}
    matched_ev = _evidence_for_requirement(req_ids, ev, ev_map)
    assert len(matched_ev) >= 1


def test_judge_parsing_case_insensitive_and_whitespace_tolerant() -> None:
    """Judge output with casing differences or surrounding whitespace must parse cleanly without errors."""
    requirements = ["Manual Testing", "Automated Testing", "API Testing"]
    evidence = [
        "Explicit skill: Manual Testing",
        "Explicit skill: Automated Testing",
        "Explicit skill: API Testing",
    ]
    raw_content = """{
        "evaluations": [
            {
                "requirement": "manual testing",
                "satisfaction_percent": 100,
                "reasoning": "Candidate lists manual testing",
                "evidence_quote": "Explicit skill: Manual Testing"
            },
            {
                "requirement": "Automated Testing ",
                "satisfaction_percent": 75,
                "reasoning": "Candidate lists automated testing",
                "evidence_quote": "Explicit skill: Automated Testing"
            },
            {
                "requirement": "api testing",
                "satisfaction_percent": 50,
                "reasoning": "Candidate lists API testing",
                "evidence_quote": "Explicit skill: API Testing"
            }
        ]
    }"""
    evals = JudgeProvider._parse(raw_content, requirements, evidence)
    assert len(evals) == 3
    assert evals[0].requirement == "Manual Testing"
    assert evals[0].satisfaction_percent == 100.0
    assert evals[1].requirement == "Automated Testing"
    assert evals[1].satisfaction_percent == 75.0
    assert evals[2].requirement == "API Testing"
    assert evals[2].satisfaction_percent == 50.0


def test_prompt_generation_is_deterministic() -> None:
    """build_prompt and build_judge_prompt must return exact identical output across multiple calls."""
    cv_text = "Experienced Python Developer with 5 years experience in Django and PostgreSQL."
    sys1, user1 = build_prompt(cv_text)
    sys2, user2 = build_prompt(cv_text)
    assert sys1 == sys2
    assert user1 == user2

    reqs = [{"requirement": "Python"}, {"requirement": "Django"}]
    ev = ["Explicit skill: Python", "Explicit skill: Django"]
    jsys1, juser1 = build_judge_prompt(reqs, ev)
    jsys2, juser2 = build_judge_prompt(reqs, ev)
    assert jsys1 == jsys2
    assert juser1 == juser2


def test_ranking_cache_key_deterministic_with_shuffled_lists() -> None:
    """ranking_cache_key must produce identical hash even if candidate skills or JD skills are in different order."""
    candidate_a = CVSchema(
        skills=["Python", "Django", "PostgreSQL"],
        inferred_skills=["Backend Development", "REST API"],
        certifications=["AWS Certified"],
    )
    candidate_b = CVSchema(
        skills=["PostgreSQL", "Python", "Django"],
        inferred_skills=["REST API", "Backend Development"],
        certifications=["AWS Certified"],
    )
    jd_a = JobDescription(
        title="Backend Engineer",
        required_skills=["Django", "Python"],
        nice_to_have_skills=["PostgreSQL", "Docker"],
    )
    jd_b = JobDescription(
        title="Backend Engineer",
        required_skills=["Python", "Django"],
        nice_to_have_skills=["Docker", "PostgreSQL"],
    )
    key_a = ranking_cache_key(candidate_a, jd_a)
    key_b = ranking_cache_key(candidate_b, jd_b)
    assert key_a == key_b


def test_ranking_cache_key_differs_by_matching_mode() -> None:
    """ranking_cache_key must produce distinct hashes for matching_mode='taxonomy' vs 'semantic'."""
    candidate = CVSchema(skills=["Python", "SQL"])
    jd_tax = JobDescription(
        title="Backend Engineer",
        required_skills=["Python", "SQL"],
        matching_mode="taxonomy",
    )
    jd_sem = JobDescription(
        title="Backend Engineer",
        required_skills=["Python", "SQL"],
        matching_mode="semantic",
    )
    key_tax = ranking_cache_key(candidate, jd_tax)
    key_sem = ranking_cache_key(candidate, jd_sem)
    assert key_tax != key_sem



def test_pipeline_reproducibility_10_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Running rank() 10 times on the exact same candidate and JD must produce 100% identical scores and breakdown."""
    def fake_query_judge(requirements: list[str], evidence: list[str]) -> JudgeResponse:
        evals = []
        for req in requirements:
            evals.append(
                SkillEvaluation(
                    requirement=req,
                    satisfaction_percent=100.0 if "Testing" in req or "Python" in req else 75.0,
                    reasoning=f"Strong evidence for {req}",
                    evidence_quote=f"Explicit skill: {req}" if f"Explicit skill: {req}" in evidence else "",
                )
            )
        return JudgeResponse(evaluations=evals, provider="mock-gemini", model="gemini-3.8-flash")

    monkeypatch.setattr("app.pipeline.ranking.query_judge", fake_query_judge)

    candidate = CVSchema(
        skills=["Manual Testing", "Automated Testing", "Test Cases", "Python", "Selenium"],
        experience=[
            Experience(
                job_title="Senior QA Engineer",
                company="Global Quality Corp",
                start_date="2019-01-01",
                end_date="2024-01-01",
                description="Designed automated test frameworks and executed regression testing.",
            )
        ],
        projects=[
            Project(
                name="Automation Suite",
                description="Built automated test suite in Python with Selenium.",
                technologies_mentioned=["Python", "Selenium"],
            )
        ],
    )
    jd = JobDescription(
        title="Senior Software Tester",
        required_skills=["Software Testing", "Automated Testing", "Test Cases", "Python"],
        nice_to_have_skills=["Selenium", "Performance Testing"],
        min_experience_years=3,
    )

    results = []
    for _ in range(10):
        # Clear cache between runs to test actual re-computation reproducibility
        _ranking_cache.clear()
        res = rank(candidate, jd)
        results.append(res)

    first = results[0]
    for i, res in enumerate(results[1:], start=2):
        assert res.score == first.score, f"Run {i} score {res.score} != first run score {first.score}"
        assert res.breakdown == first.breakdown, f"Run {i} breakdown differs from first run"
        assert len(res.skill_evaluations) == len(first.skill_evaluations)
        for e_curr, e_first in zip(res.skill_evaluations, first.skill_evaluations, strict=True):
            assert e_curr.requirement == e_first.requirement
            assert e_curr.satisfaction_percent == e_first.satisfaction_percent
            assert e_curr.source_multiplier == e_first.source_multiplier
            assert e_curr.final_skill_score == e_first.final_skill_score
