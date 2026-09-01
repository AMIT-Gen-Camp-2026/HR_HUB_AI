"""يتأكد إن require_api_key فعليًا بيحجب الطلبات لما AI_SERVICE_API_KEY يكون
متظبط، وإن الـ endpoints بتفضل شغالة عادي لما يكون فاضي (fail-open المقصود
للتطوير المحلي - انظر app/security/auth.py).
"""
from __future__ import annotations

import io

import pytest

from app import main
from app.pipeline import ranking


@pytest.fixture
def client_with_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main.config, "AI_SERVICE_API_KEY", "test-secret-key")
    monkeypatch.setattr(ranking, "semantic_fit", lambda cv, jd: 0.5)
    monkeypatch.setattr(main.config, "RANKING_ENABLED", True)
    return main.app.test_client()


def _payload() -> dict:
    return {
        "file": (io.BytesIO(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"), "candidate.pdf", "application/pdf"),
        "job_description": '{"title": "Data Analyst", "required_skills": ["Python"]}',
    }


def test_rejects_request_with_no_key(client_with_key) -> None:
    response = client_with_key.post("/api/v1/cv/evaluate", data=_payload(), content_type="multipart/form-data")
    assert response.status_code == 401
    assert response.get_json()["success"] is False


def test_rejects_request_with_wrong_key(client_with_key) -> None:
    response = client_with_key.post(
        "/api/v1/cv/evaluate",
        data=_payload(),
        content_type="multipart/form-data",
        headers={"X-API-Key": "wrong-key"},
    )
    assert response.status_code == 401


def test_accepts_request_with_correct_key(client_with_key, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "extract_raw_text", lambda filepath, ext: "CV text")
    monkeypatch.setattr(main, "clean_and_query", lambda raw_text: main.CVSchema(skills=["Python"], personal_info={"name": "Jane Doe"}))
    monkeypatch.setattr(main, "compute_ranking", lambda candidate, job_description: ranking.rank(candidate, job_description))

    response = client_with_key.post(
        "/api/v1/cv/evaluate",
        data=_payload(),
        content_type="multipart/form-data",
        headers={"X-API-Key": "test-secret-key"},
    )
    assert response.status_code == 200
    assert response.get_json()["success"] is True


def test_health_endpoint_never_requires_a_key(client_with_key) -> None:
    """/health لازم يفضل متاح من غير مفتاح - بيتستخدم في Docker HEALTHCHECK
    ومونيتورينج، مش من المفروض يعرف عن الـ auth الخاص بباقي الـ API."""
    response = client_with_key.get("/api/v1/health")
    assert response.status_code == 200


def test_endpoint_open_when_key_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """لما AI_SERVICE_API_KEY فاضي (زي حالة التطوير المحلي/الاختبارات
    الافتراضية)، الـ endpoint المفروض يفضل شغال من غير أي مفتاح - fail-open
    مقصود، موثّق في app/security/auth.py."""
    monkeypatch.setattr(main.config, "AI_SERVICE_API_KEY", "")
    monkeypatch.setattr(ranking, "semantic_fit", lambda cv, jd: 0.5)
    monkeypatch.setattr(main.config, "RANKING_ENABLED", True)
    client = main.app.test_client()
    monkeypatch.setattr(main, "extract_raw_text", lambda filepath, ext: "CV text")
    monkeypatch.setattr(main, "clean_and_query", lambda raw_text: main.CVSchema(skills=["Python"], personal_info={"name": "Jane Doe"}))
    monkeypatch.setattr(main, "compute_ranking", lambda candidate, job_description: ranking.rank(candidate, job_description))

    response = client.post(
        "/api/v1/cv/evaluate",
        data=_payload(),
        content_type="multipart/form-data",
    )
    assert response.status_code == 200