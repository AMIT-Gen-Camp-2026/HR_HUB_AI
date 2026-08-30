"""End-to-end test for the Flask /api/v1/rank endpoint (app/main.py).

semantic_fit() is monkeypatched here for the same reason as
tests/unit/test_ranking.py: no network / no real embeddings model load in
CI. This file's job is to check the HTTP wiring (status codes, JSON body,
validation errors, the kill switch) - scoring correctness itself is
already covered by test_ranking.py.
"""
from __future__ import annotations

import pytest

from app import main
from app.pipeline import ranking


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ranking, "semantic_fit", lambda cv, jd: 0.5)
    monkeypatch.setattr(main.config, "RANKING_ENABLED", True)
    # هذا الملف بيختبر منطق الـ ranking نفسه (status codes, validation, kill
    # switch) - الـ auth ليها اختبارات مخصصة في tests/integration/test_auth.py.
    # بنفضّي المفتاح هنا عشان الاختبارات دي تفضل شغالة بغض النظر عن قيمة
    # AI_SERVICE_API_KEY الحقيقية في .env بتاع المطوّر.
    monkeypatch.setattr(main.config, "AI_SERVICE_API_KEY", "")
    return main.app.test_client()

def _payload() -> dict:
    return {
        "candidate": {"skills": ["Python", "SQL"]},
        "job_description": {
            "title": "Data Analyst",
            "required_skills": ["Python", "SQL", "Tableau"],
        },
    }


def test_rank_returns_result_for_valid_payload(client) -> None:
    response = client.post("/api/v1/rank", json=_payload())

    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["result"]["matched_skills"] == ["Python", "SQL"]
    assert body["result"]["missing_skills"] == ["Tableau"]
    assert 0.0 < body["result"]["score"] < 100.0


def test_rank_rejects_non_json_body(client) -> None:
    response = client.post("/api/v1/rank", data="not json", content_type="text/plain")

    assert response.status_code == 400
    assert response.get_json()["success"] is False


def test_rank_rejects_invalid_job_description(client) -> None:
    payload = _payload()
    del payload["job_description"]["title"]  # title is required in JobDescription

    response = client.post("/api/v1/rank", json=payload)

    assert response.status_code == 422
    assert response.get_json()["success"] is False


def test_rank_respects_kill_switch(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main.config, "RANKING_ENABLED", False)

    response = client.post("/api/v1/rank", json=_payload())

    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is False
    assert "switched off" in body["error"]