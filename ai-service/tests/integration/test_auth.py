"""يتأكد إن require_api_key فعليًا بيحجب الطلبات لما AI_SERVICE_API_KEY يكون
متظبط، وإن الـ endpoints بتفضل شغالة عادي لما يكون فاضي (fail-open المقصود
للتطوير المحلي - انظر app/security/auth.py).
"""
from __future__ import annotations

import io
import json

import pytest

from app import main
from app.pipeline import ranking
from app.providers.judge_provider import JudgeResponse
from app.schemas.cv import CVSchema, SkillEvaluation


@pytest.fixture
def client_with_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main.config, "AI_SERVICE_API_KEY", "test-secret-key")
    monkeypatch.setattr(main.config, "RANKING_ENABLED", True)
    monkeypatch.setattr(main.limiter, "enabled", False)
    return main.app.test_client()


def _payload() -> dict:
    return {
        "file": (io.BytesIO(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"), "candidate.pdf", "application/pdf"),
        "job_description": json.dumps({"title": "Data Analyst", "required_skills": ["Python"]}),
    }


def _fake_judge(requirements: list[str], evidence: list[str]) -> JudgeResponse:
    return JudgeResponse(
        evaluations=[
            SkillEvaluation(
                requirement=req,
                satisfaction_percent=100.0,
                reasoning="Mocked integration judge evaluation.",
                evidence_quote=f"Explicit skill: {req}",
            )
            for req in requirements
        ],
        provider="test-judge",
        model="test-model",
    )


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
    monkeypatch.setattr(ranking, "query_judge", _fake_judge)
    monkeypatch.setattr(main, "extract_raw_text", lambda filepath, ext: "CV text")
    monkeypatch.setattr(
        main,
        "clean_and_query",
        lambda raw_text: CVSchema(skills=["Python"], personal_info={"name": "Jane Doe"}),
    )

    response = client_with_key.post(
        "/api/v1/cv/evaluate",
        data=_payload(),
        content_type="multipart/form-data",
        headers={"X-API-Key": "test-secret-key"},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["ranking"]["score"] == 80.0
    assert body["ranking"]["breakdown"]["scoring_version"] == "weighted-70-20-10-v1"
    assert body["ranking"]["breakdown"]["fallback_to_taxonomy"] is False


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
    monkeypatch.setattr(main.config, "RANKING_ENABLED", True)
    monkeypatch.setattr(ranking, "query_judge", _fake_judge)
    client = main.app.test_client()
    monkeypatch.setattr(main, "extract_raw_text", lambda filepath, ext: "CV text")
    monkeypatch.setattr(
        main,
        "clean_and_query",
        lambda raw_text: CVSchema(skills=["Python"], personal_info={"name": "Jane Doe"}),
    )

    response = client.post(
        "/api/v1/cv/evaluate",
        data=_payload(),
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["ranking"]["score"] == 80.0
    assert body["ranking"]["breakdown"]["scoring_version"] == "weighted-70-20-10-v1"
    assert body["ranking"]["breakdown"]["fallback_to_taxonomy"] is False