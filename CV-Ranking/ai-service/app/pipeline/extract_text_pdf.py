"""
extraction/pdf_extractor.py

مسؤول فقط عن استخراج النص الخام من ملفات PDF.
منقول من الـ Kaggle Notebook (extract_text_from_cv - جزء الـ PDF) مع تحسينات:
- separation of concerns: الملف ده بيتعامل مع PDF بس، DOCX في ملف منفصل
- error handling أوضح لحالات الملفات التالفة
- (جديد) x_tolerance مخفّض: لوحظ إن بعض الـ CVs (خصوصًا اللي فيها تنسيق
  أعمدة متقاربة أو مسافات ضيقة بين الفئات والقيم زي "NumPy" يتبعها
  "Machine Learning" في نفس السطر) كانت بتطلع ملتصقة ببعض بدون مسافة
  (زي "NumPyMachine Learning") مع الإعداد الافتراضي لـ pdfplumber.
  السبب: x_tolerance الافتراضي (3) بيخلي pdfplumber يعتبر حروف متقاربة
  نسبيًا جزء من نفس "الكلمة"، فمش بيحط مسافة بينهم. تقليله لـ 1 بيخلي
  pdfplumber أكتر حساسية للفراغات الحقيقية بين الكلمات فبيحافظ على
  المسافة الأصلية بدل ما يلزّقها.
"""

import os
import pdfplumber


class PDFExtractionError(Exception):
    """بترفع لو حصلت مشكلة أثناء قراءة ملف PDF (ملف تالف، محمي بباسورد، إلخ)."""
    pass


# x_tolerance منخفض عشان نتجنب التصاق كلمات متجاورة بدون مسافة
# (زي "NumPyMachine" بدل "NumPy Machine") - راجع الملاحظة فوق.
PDF_X_TOLERANCE = 1


def extract_text_from_pdf(file_path: str) -> str:
    """
    يستخرج النص الخام من ملف PDF باستخدام pdfplumber.

    Args:
        file_path: المسار الكامل لملف الـ PDF.

    Returns:
        النص المستخرج من كل صفحات الملف (مجمّع بسطر فاضي بين كل صفحة).

    Raises:
        FileNotFoundError: لو الملف مش موجود أصلاً.
        PDFExtractionError: لو الملف تالف أو مش قادرين نقرأه لأي سبب.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"الملف مش موجود: {file_path}")

    text_parts = []

    try:
        with pdfplumber.open(file_path) as pdf:
            if len(pdf.pages) == 0:
                raise PDFExtractionError("ملف الـ PDF فاضي (مفيش صفحات).")

            for page_number, page in enumerate(pdf.pages, start=1):
                try:
                    page_text = page.extract_text(x_tolerance=PDF_X_TOLERANCE) or ""
                except Exception as page_error:
                    # لو صفحة واحدة بس فيها مشكلة، منوقفش كل العملية،
                    # نسجل المشكلة ونكمل باقي الصفحات
                    page_text = ""
                    print(
                        f"⚠️ تعذر استخراج نص من الصفحة {page_number}: {page_error}"
                    )
                text_parts.append(page_text)

    except PDFExtractionError:
        raise
    except Exception as e:
        # أي مشكلة تانية في فتح الملف نفسه (تلف، تشفير، إلخ)
        raise PDFExtractionError(f"تعذر قراءة ملف الـ PDF: {e}") from e

    full_text = "\n".join(text_parts).strip()

    if not full_text:
        raise PDFExtractionError(
            "لم يتم استخراج أي نص من ملف الـ PDF. "
            "قد يكون الملف عبارة عن صور فقط (scanned) بدون طبقة نصية."
        )

    return full_text