"""
security/file_validator.py

كل منطق التحقق من أمان الملف المرفوع، معزول في مكان واحد:
1. التحقق من الامتداد
2. التحقق من المحتوى الحقيقي (magic bytes) مش بس اسم الملف
3. توليد اسم ملف آمن للتخزين المؤقت

ده كان قبل كده متوزع جوه app.py مباشرة. اتنقل هنا عشان:
- app.py يفضل بس orchestration (يستقبل request -> ينده الخطوات -> يرجع response)
- أي تعديل مستقبلي على قواعد الأمان (نوع ملفات جديد، فحص إضافي) يبقى
  في مكان واحد بدل ما يتوزع جوه route handler

(تحديث): بدل الاعتماد على مكتبة python-magic (اللي محتاجة libmagic كـ
native library غير متوفرة افتراضيًا على ويندوز)، بنتحقق يدويًا من أول
بايتات الملف (magic bytes / file signature) - نفس المبدأ بالظبط، بس
من غير أي تبعية خارجية على نظام التشغيل.
"""

import os
import uuid

from werkzeug.utils import secure_filename

# التوقيعات الثنائية (magic bytes) الحقيقية لبداية كل نوع ملف مسموح بيه.
# PDF: بيبدأ دايمًا بـ "%PDF-".
# DOCX: هو في الأساس أرشيف ZIP (Office Open XML)، فبيبدأ بتوقيع الـ ZIP القياسي.
_FILE_SIGNATURES: dict[str, list[bytes]] = {
    ".pdf": [b"%PDF-"],
    ".docx": [b"PK\x03\x04"],
}


class FileValidationError(Exception):
    """بترفع لو الملف مرفوض لأي سبب أمني (امتداد غير مسموح، محتوى مش مطابق، إلخ)."""
    pass


def validate_extension(filename: str, allowed_extensions: set[str]) -> str:
    """
    بتتحقق من امتداد الملف وترجعه (lowercase) لو مسموح بيه.

    Raises:
        FileValidationError: لو الامتداد مش مسموح.
    """
    ext = os.path.splitext(filename)[1].lower()
    if ext not in allowed_extensions:
        raise FileValidationError(
            f"Unsupported file extension: {ext}. Allowed: {sorted(allowed_extensions)}"
        )
    return ext


def validate_file_content(filepath: str, ext: str) -> None:
    """
    بتتأكد إن محتوى الملف الفعلي (أول بايتات منه) بيتطابق مع الامتداد المعلن،
    عن طريق مقارنتها بالتوقيع الثنائي (magic bytes) المعروف لكل نوع.
    ده بيمنع حد يسمي ملف مش pdf/docx فعليًا بامتداد .pdf أو .docx ويرفعه.

    Raises:
        FileValidationError: لو المحتوى مش مطابق للامتداد، أو تعذر
            قراءة الملف أصلاً.
    """
    signatures = _FILE_SIGNATURES.get(ext)
    if not signatures:
        raise FileValidationError(f"No known signature for extension: {ext}")

    try:
        with open(filepath, "rb") as f:
            header = f.read(8)
    except Exception as e:
        raise FileValidationError(f"Could not read file content: {e}") from e

    if not any(header.startswith(sig) for sig in signatures):
        raise FileValidationError(
            f"File content does not match declared extension ({ext})."
        )


def generate_safe_storage_name(original_filename: str) -> str:
    """
    بتولّد اسم ملف آمن للتخزين المؤقت: uuid عشوائي + نسخة منظفة من
    الاسم الأصلي (بس للقراءة/الـ logs، مش بيتم الاعتماد عليه في المسار).

    ده بيمنع path traversal (اسم ملف فيه ../../) وبيمنع تصادم/استبدال
    ملفات لو اتنين رفعوا ملف بنفس الاسم في نفس الوقت.
    """
    safe_name = secure_filename(original_filename)
    return f"{uuid.uuid4().hex}_{safe_name}"