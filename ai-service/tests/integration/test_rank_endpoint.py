"""End-to-end test for the merged CV extraction + ranking endpoint.

The underlying ranking logic is checked in the unit tests; this suite covers
HTTP wiring, validation, the kill switch, and the single-call flow.
"""
from __future__ import annotations

import io
import json

import pytest

from app import main
from app.pipeline import ranking
from app.providers.hf_provider import ModelInferenceError
from app.schemas.cv import CVSchema


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ranking, "semantic_fit", lambda cv, jd: 0.5)
    monkeypatch.setattr(main.config, "RANKING_ENABLED", True)
    monkeypatch.setattr(main.config, "AI_SERVICE_API_KEY", "")
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
    monkeypatch.setattr(main, "compute_ranking", lambda candidate, job_description: ranking.rank(candidate, job_description))

    response = client.post("/api/v1/cv/evaluate", data=_multipart_data(), content_type="multipart/form-data")

    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["cv"]["skills"] == ["Python", "SQL"]
    assert body["ranking"]["matched_skills"] == ["Python", "SQL"]
    assert body["ranking"]["missing_skills"] == ["Tableau"]
    assert 0.0 < body["ranking"]["score"] < 100.0


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
    monkeypatch.setattr(main, "compute_ranking", lambda candidate, job_description: ranking.rank(candidate, job_description))

    response = client.post(
        "/api/v1/cv/evaluate", data=_multipart_data(), content_type="multipart/form-data"
    )

    assert response.status_code == 200
    assert isinstance(response.get_json()["extraction_metadata"], dict)