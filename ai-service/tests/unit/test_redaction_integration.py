"""يتأكد إن clean_and_query() فعليًا بتشيل الـ PII قبل ما تبني الـ prompt،
وإن personal_info.email/phone لسه بترجع صح رغم كده (مستخرجة محليًا بالـ regex،
مش من الموديل). query_model متعمل له monkeypatch هنا - الهدف اختبار الـ wiring
نفسه (redact -> build_prompt -> query_model)، مش دقة الموديل.
"""
from __future__ import annotations

from app.pipeline import run
from app.schemas.cv import CVSchema

RAW_CV = """
Ahmed Hassan
Email: ahmed.hassan@example.com
Mobile: 01012345678
National ID: 29803081402633

Experience:
Backend Engineer at Acme Corp — built REST APIs with Django and PostgreSQL.
"""


def test_pii_never_reaches_the_model(monkeypatch) -> None:
    captured_prompts: list[str] = []

    def fake_query_model(system_prompt, user_prompt, validate_fn):
        captured_prompts.append(system_prompt + user_prompt)
        # نرجّع CVSchema فاضي - مش مهتمين هنا بمخرجات الموديل نفسه
        return CVSchema()

    monkeypatch.setattr(run, "query_model", fake_query_model)

    result = run.clean_and_query(RAW_CV)

    sent_payload = captured_prompts[0]
    assert "ahmed.hassan@example.com" not in sent_payload
    assert "01012345678" not in sent_payload
    assert "29803081402633" not in sent_payload

    # لكن الـ CVSchema الراجع لازم يكون فيه الإيميل/التليفون الحقيقيين -
    # مستخرجين محليًا بالـ regex، رغم إن الموديل نفسه ما شافهمش خالص.
    assert result.personal_info.email == "ahmed.hassan@example.com"
    assert result.personal_info.phone == "01012345678"


def test_model_output_email_is_overridden_by_local_extraction(monkeypatch) -> None:
    """لو الموديل (غلط) رجّع إيميل مختلف من نفسه، القيمة المستخرجة محليًا
    من النص الأصلي هي اللي المفروض تكسب - هي الأدق والوحيدة المضمونة."""

    def fake_query_model(system_prompt, user_prompt, validate_fn):
        cv = CVSchema()
        cv.personal_info.email = "hallucinated@wrong.com"
        return cv

    monkeypatch.setattr(run, "query_model", fake_query_model)

    result = run.clean_and_query(RAW_CV)

    assert result.personal_info.email == "ahmed.hassan@example.com" 