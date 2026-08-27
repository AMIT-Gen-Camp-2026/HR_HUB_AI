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
    بتاخد النص الخام، تنضفه، تبني الـ prompt عن طريق build_prompt() الثابتة،
    وتستدعي hf_provider.query_model() مباشرة مع الـ validation + fallback
    chain بتاعته.

    Raises:
        ModelInferenceError: فشل الاستدلال عبر كل الموديلات في MODEL_CHAIN.
    """
    cleaned_text = clean_cv_text(raw_text)
    system_prompt, user_prompt = build_prompt(cleaned_text)
    return query_model(system_prompt, user_prompt, validate_fn=parse_and_validate)
