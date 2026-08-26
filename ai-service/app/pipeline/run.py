"""
app/pipeline/run.py

بيربط خطوات الـ pipeline كلها ورا بعض: extract -> normalize -> prompt -> model -> validate.
ده المكان اللي فيه orchestration بس - مفيش أي HTTP/Flask logic هنا خالص.

المنطق ده كان قبل كده متوزع مباشرة جوه route handler في app.py القديم.
اتنقل هنا حرفيًا زي ما هو (نفس الخطوات، نفس الترتيب، نفس الـ exceptions) عشان:
- app/main.py يفضل مسؤول بس عن HTTP concerns (request/response/status codes)
- منطق الـ pipeline نفسه يبقى قابل لإعادة الاستخدام (من CLI أو test أو worker)
  من غير ما يكون مربوط بـ Flask

Sprint 2 — إضافة run_cv_extraction():
clean_and_query() القديمة بتستورد build_prompt و query_model بشكل ثابت
من hf_provider مباشرة. الـ route الجديد (routes_cv.py) محتاج نسخة بتستقبل
provider و prompts كـ dependency injection (عشان StubProvider يقدر
يحل محل الموديل الحقيقي وقت التستات) - فـ run_cv_extraction() هي النسخة
دي، وبتاخد بايتس الملف مباشرة (مش filepath) عشان كده متوافقة مع شكل
الملف المرفوع في FastAPI (UploadFile.read()). clean_and_query() القديمة
اتسابت زي ما هي من غير تعديل - لسه مستخدمة في app/main.py (Flask) القديم.
"""

import tempfile
from pathlib import Path

from pydantic import ValidationError as PydanticValidationError

from app.errors import SchemaValidationFailed
from app.pipeline.extract_text_docx import extract_text_from_docx
from app.pipeline.extract_text_pdf import extract_text_from_pdf
from app.pipeline.normalize import clean_cv_text
from app.pipeline.postprocess import (
    JSONExtractionError,
    extract_json_from_model_output,
    normalize_model_output,
)
from app.prompts.registry import PromptRegistry, build_prompt
from app.providers.base import ProviderAdapter
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
    (العالم القديم - Flask) بتاخد النص الخام، تنضفه، تبني الـ prompt عن
    طريق build_prompt() الثابتة، وتستدعي hf_provider.query_model() مباشرة
    مع الـ validation + fallback chain بتاعته.

    Raises:
        ModelInferenceError: فشل الاستدلال عبر كل الموديلات في MODEL_CHAIN.
    """
    cleaned_text = clean_cv_text(raw_text)
    system_prompt, user_prompt = build_prompt(cleaned_text)
    return query_model(system_prompt, user_prompt, validate_fn=parse_and_validate)


def _write_temp_file(content: bytes, ext: str) -> str:
    """
    بتكتب البايتس في ملف مؤقت وترجع مساره. بتقفل الملف قبل ما ترجعه
    عشان extract_text_from_pdf/docx يقدروا يفتحوه من غير مشاكل قفل
    ملفات على Windows.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    try:
        tmp.write(content)
    finally:
        tmp.close()
    return tmp.name


async def run_cv_extraction(
    filename: str,
    content: bytes,
    provider: ProviderAdapter,
    prompts: PromptRegistry,
) -> CVSchema:
    """
    (العالم الجديد - FastAPI) نفس منطق clean_and_query() بالظبط، بس
    بتستخدم provider و prompts المحقونين بدل الاستيرادات الثابتة، وبتاخد
    بايتس الملف مباشرة بدل filepath جاهز على القرص.

    ملحوظتين عن الفرق عن clean_and_query():

    1. ProviderAdapter.complete() بتاخد prompt نص واحد بس - مفيش system/user
       منفصلين في العقد بتاعه. فبندمج system_prompt و user_prompt الناتجين
       من prompts.build_cv_extraction_prompt() في نص واحد قبل ما نبعتهم.
       الـ randomized delimiters حوالين نص الـ CV نفسه (جوه user_prompt)
       متأثرتش - لسه موجودة زي ما هي جوه النص المدموج.

    2. parse_and_validate() بترمي JSONExtractionError/pydantic.ValidationError
       مباشرة، ودول مش AIServiceError subclasses فمش هيتمسكوا في
       register_exception_handlers(). بنلفهم هنا في SchemaValidationFailed
       (422) عشان نلتزم بمبدأ "one error envelope for every failure".

    Raises:
        ValueError: امتداد غير مدعوم.
        SchemaValidationFailed: فشل تحليل/التحقق من ناتج الموديل.
        ProviderUnavailable: فشل الاستدلال عند الـ provider (بترمى منه مباشرة).
    """
    ext = Path(filename).suffix.lower()
    if ext not in (".pdf", ".docx"):
        raise ValueError(f"Unsupported extension: {ext}")

    tmp_path = _write_temp_file(content, ext)
    try:
        raw_text = extract_raw_text(tmp_path, ext)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    cleaned_text = clean_cv_text(raw_text)
    system_prompt, user_prompt = prompts.build_cv_extraction_prompt(cleaned_text)
    full_prompt = f"{system_prompt}\n\n{user_prompt}"

    completion = await provider.complete(full_prompt, schema=CVSchema)

    try:
        return parse_and_validate(completion.text)
    except (JSONExtractionError, PydanticValidationError) as exc:
        raise SchemaValidationFailed(str(exc)) from exc