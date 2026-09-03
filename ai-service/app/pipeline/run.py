"""
app/pipeline/run.py

بيربط خطوات الـ pipeline كلها ورا بعض: extract -> normalize -> prompt -> model -> validate.
ده المكان اللي فيه orchestration بس - مفيش أي HTTP/Flask logic هنا خالص.

المنطق ده كان قبل كده متوزع مباشرة جوه route handler في app.py القديم.
اتنقل هنا حرفيًا زي ما هو (نفس الخطوات، نفس الترتيب، نفس الـ exceptions) عشان:
- app/main.py يفضل مسؤول بس عن HTTP concerns (request/response/status codes)
- منطق الـ pipeline نفسه يبقى قابل لإعادة الاستخدام (من CLI أو test أو worker)
  من غير ما يكون مربوط بـ Flask

ملحوظة تنضيف: كان فيه هنا نسخة تانية (run_cv_extraction) بتعتمد على
ProviderAdapter/PromptRegistry بتوع مسار الـ FastAPI اللي اتشال لأنه مكنش
متوصّل (مفيش حاجة كانت بتعمل build_provider() فعليًا وقت الـ runtime).
اتشالت من هنا عشان الملف يفضل قابل للاستيراد من غير ImportError. المسار
الوحيد الشغال دلوقتي هو clean_and_query() -> app/main.py (Flask).
"""

import hashlib
import inspect
import json
import time
from collections import OrderedDict

from app.pipeline.extract_text_docx import extract_text_from_docx
from app.pipeline.extract_text_pdf import extract_text_from_pdf
from app.pipeline.normalize import clean_cv_text
from app.pipeline.postprocess import (
    extract_json_from_model_output,
    normalize_model_output,
)
from app.pipeline.redact import assert_clean, extract_contact_info, redact
from app.prompts.registry import build_prompt
from app.providers.hf_provider import query_model
from app.schemas.cv import CVSchema
from app.skills.canonicalize import canonicalise, extract_explicit_skills
from config.settings import config

EXTRACTION_PROMPT_VERSION = "cv-extraction-v1"
SCHEMA_VERSION = "cv-schema-v1"
TAXONOMY_VERSION = "2026.09"
SNAPSHOT_TTL_SECONDS = 3600.0
SNAPSHOT_MAX_ENTRIES = 128
_snapshot_cache: OrderedDict[str, tuple[float, dict]] = OrderedDict()
_last_extraction_metadata: dict[str, object] = {}


def get_extraction_metadata() -> dict[str, object]:
    return dict(_last_extraction_metadata)


def _snapshot_key(cleaned_text: str) -> str:
    configuration = {
        "document_hash": hashlib.sha256(cleaned_text.encode("utf-8")).hexdigest(),
        "prompt_version": EXTRACTION_PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "models": config.MODEL_CHAIN,
    }
    return hashlib.sha256(
        json.dumps(configuration, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _get_cached_snapshot(cache_key: str) -> dict | None:
    entry = _snapshot_cache.get(cache_key)
    if entry is None:
        return None
    created_at, payload = entry
    if time.monotonic() - created_at >= SNAPSHOT_TTL_SECONDS:
        del _snapshot_cache[cache_key]
        return None
    _snapshot_cache.move_to_end(cache_key)
    return payload


def _store_snapshot(cache_key: str, payload: dict) -> None:
    _snapshot_cache[cache_key] = (time.monotonic(), payload)
    _snapshot_cache.move_to_end(cache_key)
    while len(_snapshot_cache) > SNAPSHOT_MAX_ENTRIES:
        _snapshot_cache.popitem(last=False)


def extraction_status(cv: CVSchema) -> str:
    """Classify successful extraction without confusing it with model failure."""
    has_evidence = any(
        (
            cv.skills,
            cv.inferred_skills,
            cv.experience,
            cv.projects,
            cv.education,
            cv.certifications,
            cv.languages,
            cv.personal_info.name,
        )
    )
    return "SUCCESS" if has_evidence else "EMPTY"


def extract_raw_text(filepath: str, ext: str) -> str:
    """بتستدعي الـ extractor المناسب حسب امتداد الملف."""
    if ext == ".pdf":
        return extract_text_from_pdf(filepath)
    if ext == ".docx":
        return extract_text_from_docx(filepath)
    raise ValueError(f"Unsupported extension: {ext}")


def parse_and_validate(raw_output: str) -> CVSchema:
    """
    بتتحول من نص خام لموديل واحد إلى CVSchema متحقق منها بالكامل.

    Raises:
        JSONExtractionError: لو تعذر استخراج/تحليل JSON من النص.
        pydantic.ValidationError: لو الـ JSON متحلل لكن مش مطابق للـ schema.
    """
    raw_cv_data = extract_json_from_model_output(raw_output)
    raw_cv_data = normalize_model_output(raw_cv_data)
    return CVSchema(**raw_cv_data)


def clean_and_query(raw_text: str) -> CVSchema:
    """
    بتاخد النص الخام، تنضفه، تشيل منه الـ PII (redact) قبل ما يتبنى منه أي prompt،
    تبني الـ prompt عن طريق build_prompt() الثابتة، وتستدعي hf_provider.query_model()
    مباشرة مع الـ validation + fallback chain بتاعته.

    ملحوظة تصميم مهمة: email و phone بيتشالوا من النص المرسل للموديل (زي أي PII
    تاني)، لكن schema الناتج لازم يفضل فيه القيمتين دول. الحل: بنستخرجهم بـ regex
    من النص الأصلي *قبل* الـ redact (deterministic، مفيش داعي لموديل خارجي أصلاً)،
    ونحطهم في الـ CVSchema الراجع بعد ما الموديل يرد - بدل ما نسيب الموديل يحاول
    يقرا إيميل/تليفون هو أصلاً متبعتلوش.

    Raises:
        ModelInferenceError: فشل الاستدلال عبر كل الموديلات في MODEL_CHAIN.
    """
    cleaned_text = clean_cv_text(raw_text)
    cache_key = _snapshot_key(cleaned_text)

    # لازم نستخرج الـ contact info قبل الـ redact - بعد الـ redact مفيش إيميل/تليفون
    # حقيقي يتقرا خالص، هيبقوا استبدلوا بـ [EMAIL]/[PHONE].
    contact_info = extract_contact_info(cleaned_text)

    cached = _get_cached_snapshot(cache_key)
    if cached is not None:
        try:
            cv = CVSchema(**cached["cv"])
            _last_extraction_metadata.clear()
            _last_extraction_metadata.update(
                {
                    "cache_hit": True,
                    "model_used": "versioned-in-memory-snapshot",
                    "provider": None,
                    "attempt_number": 0,
                    "fallback_occurred": False,
                    "taxonomy_recovered_skills": cached.get(
                        "taxonomy_recovered_skills", []
                    ),
                }
            )
            if contact_info["email"]:
                cv.personal_info.email = contact_info["email"]
            if contact_info["phone"]:
                cv.personal_info.phone = contact_info["phone"]
            return cv
        except Exception:
            _snapshot_cache.pop(cache_key, None)

    # نشيل PII (إيميل، تليفون، رقم قومي، أي رقم طويل) قبل ما النص يسيب المنصة
    # لأي third-party model provider (HF Inference Providers).
    redacted_text, _removed_count = redact(cleaned_text)

    system_prompt, user_prompt = build_prompt(redacted_text)

    # Safety net: لو أي identifier اتسرب رغم الـ redact() (bug في الـ regex نفسه
    # أو حالة حافة مش متغطية)، نرفض نبعت الـ payload خالص بدل ما نكمل. ده نفس
    # القاعدة الموصوفة في docstring app/pipeline/redact.py.
    assert_clean(system_prompt + user_prompt)

    model_metadata: dict[str, object] = {}
    if "metadata" in inspect.signature(query_model).parameters:
        cv = query_model(
            system_prompt,
            user_prompt,
            validate_fn=parse_and_validate,
            metadata=model_metadata,
        )
    else:
        # Preserve compatibility with tests/adapters implementing the old API.
        cv = query_model(system_prompt, user_prompt, validate_fn=parse_and_validate)

    # Preserve explicit taxonomy skills even when the model places them in an
    # inferred category instead of the literal skills field.
    explicit_skills = extract_explicit_skills(redacted_text)
    model_skill_ids = {
        canonicalise(skill)
        for skill in cv.skills + cv.inferred_skills
        if canonicalise(skill) is not None
    }
    taxonomy_recovered_skills = [
        skill
        for skill in explicit_skills
        if canonicalise(skill) not in model_skill_ids
    ]
    cv.skills = list(dict.fromkeys(cv.skills + explicit_skills))
    _store_snapshot(
        cache_key,
        {
            "cv": cv.model_dump(),
            "taxonomy_recovered_skills": taxonomy_recovered_skills,
        },
    )
    _last_extraction_metadata.clear()
    _last_extraction_metadata.update(
        {
            "cache_hit": False,
            "taxonomy_recovered_skills": taxonomy_recovered_skills,
            **model_metadata,
        }
    )

    # نفضّل القيمة اللي استخرجناها إحنا بالـ regex (أدق ومضمونة) فوق أي حاجة
    # رجّعها الموديل - أصلاً الموديل مبقاش شايف الإيميل/التليفون الحقيقيين.
    if contact_info["email"]:
        cv.personal_info.email = contact_info["email"]
    if contact_info["phone"]:
        cv.personal_info.phone = contact_info["phone"]

    return cv