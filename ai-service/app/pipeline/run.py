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

    # لازم نستخرج الـ contact info قبل الـ redact - بعد الـ redact مفيش إيميل/تليفون
    # حقيقي يتقرا خالص، هيبقوا استبدلوا بـ [EMAIL]/[PHONE].
    contact_info = extract_contact_info(cleaned_text)

    # نشيل PII (إيميل، تليفون، رقم قومي، أي رقم طويل) قبل ما النص يسيب المنصة
    # لأي third-party model provider (HF Inference Providers).
    redacted_text, _removed_count = redact(cleaned_text)

    system_prompt, user_prompt = build_prompt(redacted_text)

    # Safety net: لو أي identifier اتسرب رغم الـ redact() (bug في الـ regex نفسه
    # أو حالة حافة مش متغطية)، نرفض نبعت الـ payload خالص بدل ما نكمل. ده نفس
    # القاعدة الموصوفة في docstring app/pipeline/redact.py.
    assert_clean(system_prompt + user_prompt)

    cv = query_model(system_prompt, user_prompt, validate_fn=parse_and_validate)

    # نفضّل القيمة اللي استخرجناها إحنا بالـ regex (أدق ومضمونة) فوق أي حاجة
    # رجّعها الموديل - أصلاً الموديل مبقاش شايف الإيميل/التليفون الحقيقيين.
    if contact_info["email"]:
        cv.personal_info.email = contact_info["email"]
    if contact_info["phone"]:
        cv.personal_info.phone = contact_info["phone"]

    return cv