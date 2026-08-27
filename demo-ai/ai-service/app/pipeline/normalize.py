"""
extraction/text_cleaner.py

ملف جديد (مش موجود في الـ Notebook الأصلي).
وظيفته: تنظيف النص الخام اللي طالع من pdf_extractor / docx_extractor
قبل ما يتبعت للموديل.

مهم أوي نوضح حاجة: الملف ده بينضّف الشكل (formatting) بس.
مش بيحاول "يفلتر" أو "يحذف" محاولات الـ prompt injection —
الحماية من الـ injection مسؤولية الـ security/ layer والـ system prompt،
مش الملف ده. الفصل ده مقصود عشان منعتمدش على تنظيف نص كحل أمني
(زي ما اتفقنا: مينفعش نعتمد على keyword blacklists).
"""

import re
import unicodedata


# حد أقصى لطول النص المسموح بيه بعد التنظيف (بالحروف).
# ده بيحمي من: (1) إرسال نصوص ضخمة جدًا للموديل بتكلفة عالية،
# (2) محاولات إغراق الـ context window (resource exhaustion).
MAX_TEXT_LENGTH = 20000


def clean_cv_text(raw_text: str) -> str:
    """
    بينضّف النص الخام المستخرج من ملف الـ CV.

    الخطوات:
    1. Unicode normalization (توحيد شكل الحروف، خصوصًا للعربي/الرموز الخاصة).
    2. إزالة الـ control characters اللي ممكن تتسبب في مشاكل عرض أو حقن غريب
       (زي null bytes، أو حروف invisible بتتحكم في اتجاه النص RTL/LTR
       واللي ممكن تتستخدم لإخفاء نص injection عن العين المجردة).
    3. توحيد المسافات المتكررة والأسطر الفاضية الزيادة.
    4. قص النص لو تجاوز الحد الأقصى المسموح.

    Args:
        raw_text: النص الخام من extract_text_from_pdf / extract_text_from_docx.

    Returns:
        نص منظف وجاهز يتبعت للموديل.
    """
    if not raw_text:
        return ""

    text = unicodedata.normalize("NFKC", raw_text)

    # إزالة control characters (0x00-0x1F, 0x7F) ما عدا newline و tab
    # وكمان إزالة bidi control characters (زي RLO/LRO/RLE/LRE) اللي
    # ممكن تستخدم لإخفاء نص injection بصريًا
    control_chars_pattern = re.compile(
        r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F"
        r"\u200e\u200f\u202a-\u202e\u2066-\u2069]"
    )
    text = control_chars_pattern.sub("", text)

    # توحيد المسافات المتكررة (بس مش newlines)
    text = re.sub(r"[ \t]+", " ", text)

    # توحيد الأسطر الفاضية المتكررة (أكتر من سطرين فاضيين -> سطرين بس)
    text = re.sub(r"\n{3,}", "\n\n", text)

    text = text.strip()

    if len(text) > MAX_TEXT_LENGTH:
        text = text[:MAX_TEXT_LENGTH]

    return text