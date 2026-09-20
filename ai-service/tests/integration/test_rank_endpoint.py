"""End-to-end test for the merged CV extraction + ranking endpoint.

The underlying ranking logic is checked in the unit tests; this suite covers
HTTP wiring, validation, the kill switch, and the single-call flow.
"""
from __future__ import annotations

import io
import json

import pytest

from app import main
from app.providers.hf_provider import ModelInferenceError
from app.schemas.cv import CVSchema, RankingResult


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main.config, "RANKING_ENABLED", True)
    monkeypatch.setattr(main.config, "AI_SERVICE_API_KEY", "")
    monkeypatch.setattr(main.limiter, "enabled", False)
    return main.app.test_client()


def _job_description() -> dict:
    return {
        "title": "Data Analyst",
        "required_skills": ["Python", "SQL", "Tableau"],
    }


def _multipart_data(file_bytes: bytes | None = None, job_description: dict | None = None):
    file_bytes = file_bytes or b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
    job_description = job_description or _job_description()
    return {
        "file": (io.BytesIO(file_bytes), "candidate.pdf", "application/pdf"),
        "job_description": json.dumps(job_description),
    }


def _ranking_result() -> RankingResult:
    return RankingResult(
        score=50.0,
        skill_evaluations=[],
        breakdown={"required_skills_total": 3},
    )


def test_evaluate_returns_cv_and_ranking_for_valid_payload(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "extract_raw_text", lambda filepath, ext: "CV text")
    monkeypatch.setattr(
        main,
        "clean_and_query",
        lambda raw_text: CVSchema(
            skills=["Python", "SQL"],
            inferred_skills=["Pandas"],
            personal_info={"name": "Jane Doe"},
        ),
    )
    monkeypatch.setattr(main, "compute_ranking", lambda candidate, job_description: _ranking_result())

    response = client.post("/api/v1/cv/evaluate", data=_multipart_data(), content_type="multipart/form-data")

    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["cv"]["skills"] == ["Python", "SQL"]
    assert body["ranking"]["skill_evaluations"] == []
    assert body["ranking"]["score"] == 50.0


def test_evaluate_rejects_missing_job_description(client) -> None:
    response = client.post(
        "/api/v1/cv/evaluate",
        data={"file": (io.BytesIO(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"), "candidate.pdf", "application/pdf")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json()["success"] is False


def test_evaluate_rejects_invalid_job_description_payload(client) -> None:
    response = client.post(
        "/api/v1/cv/evaluate",
        data={
            "file": (io.BytesIO(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"), "candidate.pdf", "application/pdf"),
            "job_description": '{"required_skills": ["Python"]}',
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 422
    assert response.get_json()["success"] is False


def test_evaluate_rejects_invalid_file(client) -> None:
    response = client.post(
        "/api/v1/cv/evaluate",
        data={
            "file": (io.BytesIO(b"not a real pdf"), "candidate.txt", "text/plain"),
            "job_description": json.dumps(_job_description()),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json()["success"] is False


def test_evaluate_respects_kill_switch(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "extract_raw_text", lambda filepath, ext: "CV text")
    monkeypatch.setattr(
        main,
        "clean_and_query",
        lambda raw_text: CVSchema(skills=["Python"], personal_info={"name": "Jane Doe"}),
    )
    monkeypatch.setattr(main.config, "RANKING_ENABLED", False)

    response = client.post("/api/v1/cv/evaluate", data=_multipart_data(), content_type="multipart/form-data")

    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["ranking"] is None
    assert body["cv"]["skills"] == ["Python"]


def test_evaluate_reports_failed_extraction_without_ranking(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main, "extract_raw_text", lambda filepath, ext: "CV text")
    monkeypatch.setattr(
        main,
        "clean_and_query",
        lambda raw_text: (_ for _ in ()).throw(ModelInferenceError("provider failed")),
    )

    response = client.post(
        "/api/v1/cv/evaluate", data=_multipart_data(), content_type="multipart/form-data"
    )

    assert response.status_code == 502
    body = response.get_json()
    assert body["extraction_status"] == "FAILED"
    assert "ranking" not in body


def test_evaluate_does_not_rank_empty_extraction(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "extract_raw_text", lambda filepath, ext: "CV text")
    monkeypatch.setattr(main, "clean_and_query", lambda raw_text: CVSchema())
    monkeypatch.setattr(main, "compute_ranking", lambda candidate, job_description: pytest.fail("ranked empty CV"))

    response = client.post(
        "/api/v1/cv/evaluate", data=_multipart_data(), content_type="multipart/form-data"
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["extraction_status"] == "EMPTY"
    assert body["ranking"] is None


def test_evaluate_exposes_extraction_metadata(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "extract_raw_text", lambda filepath, ext: "CV text")
    monkeypatch.setattr(main, "clean_and_query", lambda raw_text: CVSchema(skills=["Python"]))
    monkeypatch.setattr(main, "compute_ranking", lambda candidate, job_description: _ranking_result())

    response = client.post(
        "/api/v1/cv/evaluate", data=_multipart_data(), content_type="multipart/form-data"
    )

    assert response.status_code == 200
    assert isinstance(response.get_json()["extraction_metadata"], dict)


def test_evaluate_accepts_and_executes_semantic_matching_mode(client, monkeypatch: pytest.MonkeyPatch) -> None:
    """API endpoint correctly parses matching_mode='semantic' and propagates it to ranking layer."""
    received_mode: list[str] = []

    def mock_compute_ranking(candidate, jd):
        received_mode.append(jd.matching_mode)
        return RankingResult(
            score=85.0,
            skill_evaluations=[],
            breakdown={
                "scoring_version": "weighted-70-20-10-v1",
                "judge_prompt_version": "semantic-judge-v1",
                "fallback_to_taxonomy": False,
            },
        )

    monkeypatch.setattr(main, "extract_raw_text", lambda filepath, ext: "CV text")
    monkeypatch.setattr(main, "clean_and_query", lambda raw_text: CVSchema(skills=["Python"]))
    monkeypatch.setattr(main, "compute_ranking", mock_compute_ranking)

    jd_payload = {
        "title": "Data Analyst",
        "required_skills": ["Python", "SQL"],
        "matching_mode": "semantic",
    }
    response = client.post(
        "/api/v1/cv/evaluate",
        data=_multipart_data(job_description=jd_payload),
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert received_mode == ["semantic"]
    assert body["ranking"]["score"] == 85.0
    assert body["ranking"]["breakdown"]["judge_prompt_version"] == "semantic-judge-v1"
    assert body["ranking"]["breakdown"]["fallback_to_taxonomy"] is False


def test_evaluate_rejects_invalid_matching_mode(client) -> None:
    """API endpoint rejects invalid matching_mode (e.g. 'fuzzy') with HTTP 422 validation error."""
    jd_payload = {
        "title": "Data Analyst",
        "required_skills": ["Python"],
        "matching_mode": "fuzzy",
    }
    response = client.post(
        "/api/v1/cv/evaluate",
        data=_multipart_data(job_description=jd_payload),
        content_type="multipart/form-data",
    )

    assert response.status_code == 422
    body = response.get_json()
    assert body["success"] is False


def test_evaluate_taxonomy_mode_returns_fallback_to_taxonomy_false(client, monkeypatch: pytest.MonkeyPatch) -> None:
    """API endpoint in default/taxonomy mode returns breakdown with fallback_to_taxonomy: False."""
    monkeypatch.setattr(main, "extract_raw_text", lambda filepath, ext: "CV text")
    monkeypatch.setattr(main, "clean_and_query", lambda raw_text: CVSchema(skills=["Python"]))
    monkeypatch.setattr(
        main,
        "compute_ranking",
        lambda candidate, jd: RankingResult(
            score=70.0,
            skill_evaluations=[],
            breakdown={
                "scoring_version": "weighted-70-20-10-v1",
                "judge_prompt_version": "ranking-judge-v1",
                "fallback_to_taxonomy": False,
            },
        ),
    )

    response = client.post(
        "/api/v1/cv/evaluate",
        data=_multipart_data(),
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["ranking"]["breakdown"]["fallback_to_taxonomy"] is False


def test_evaluate_rejects_malformed_json_job_description(client) -> None:
    """Endpoint returns 400 when job_description is not valid JSON."""
    response = client.post(
        "/api/v1/cv/evaluate",
        data={
            "file": (io.BytesIO(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"), "candidate.pdf", "application/pdf"),
            "job_description": "not-valid-json",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "job_description must be valid JSON."


def test_evaluate_rejects_non_dict_json_job_description(client) -> None:
    """Endpoint returns 400 when job_description JSON is not a JSON object."""
    response = client.post(
        "/api/v1/cv/evaluate",
        data={
            "file": (io.BytesIO(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"), "candidate.pdf", "application/pdf"),
            "job_description": json.dumps(["not", "a", "dict"]),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "job_description must be a JSON object."


def test_evaluate_rejects_empty_filename(client) -> None:
    """Endpoint returns 400 when file has an empty filename."""
    response = client.post(
        "/api/v1/cv/evaluate",
        data={
            "file": (io.BytesIO(b"data"), "", "application/pdf"),
            "job_description": json.dumps(_job_description()),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "No file selected."


def test_evaluate_rejects_missing_file_field(client) -> None:
    """Endpoint returns 400 when 'file' field is missing from form-data."""
    response = client.post(
        "/api/v1/cv/evaluate",
        data={"job_description": json.dumps(_job_description())},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "No 'file' field in form-data."


def test_evaluate_handles_ranking_judge_error(client, monkeypatch: pytest.MonkeyPatch) -> None:
    """Endpoint returns 502 when compute_ranking encounters a JudgeProviderError."""
    from app.providers.judge_provider import JudgeProviderError

    monkeypatch.setattr(main, "extract_raw_text", lambda filepath, ext: "CV text")
    monkeypatch.setattr(main, "clean_and_query", lambda raw_text: CVSchema(skills=["Python"]))
    monkeypatch.setattr(
        main,
        "compute_ranking",
        lambda candidate, jd: (_ for _ in ()).throw(JudgeProviderError("All providers failed")),
    )

    response = client.post(
        "/api/v1/cv/evaluate",
        data=_multipart_data(),
        content_type="multipart/form-data",
    )
    assert response.status_code == 502
    body = response.get_json()
    assert body["success"] is False
    assert "Ranking model inference failed" in body["error"]
