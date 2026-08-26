r"""
utils/json_parser.py

مسؤول عن استخراج أول JSON object صحيح من النص الخام اللي بيرجّعه الموديل.

بالمقارنة بالـ Notebook الأصلي (اللي كان بيستخدم regex بسيط: r"\{.*\}"):
المشكلة في الـ regex القديم إنه "greedy" - يعني لو النص فيه أكتر من
{...} (حتى لو جوه string داخل الـ JSON نفسه)، ممكن ياخد حتة غلط أو
يفشل تمامًا مع nested objects معقدة.

هنا بدل الـ regex، بنعمل "brace counting" حقيقي: بندور على أول '{'،
وبعدين بنعدّ الأقواس المفتوحة والمقفولة واحد واحد (مع احترام الأقواس
اللي جوه strings عشان منتلخبطش)، لحد ما نلاقي الـ '}' اللي بيقفل
الـ object الأساسي بالظبط.
"""

import json


class JSONExtractionError(Exception):
    """بترفع لو تعذر استخراج JSON صحيح من نص الموديل."""
    pass


def _find_balanced_json(text: str) -> str:
    """
    بتدور على أول '{' في النص، وبعدين بتعدّ الأقواس المتوازنة
    (مع تجاهل أي '{' أو '}' لو كانت جوه string) لحد ما تلاقي
    القوس المقفول المطابق للقوس الأول.

    Returns:
        الـ substring اللي فيها أول JSON object متوازن بالكامل.

    Raises:
        JSONExtractionError: لو مفيش '{' في النص، أو لو الأقواس
                              مش متوازنة (النص اتقطع قبل ما يخلص).
    """
    start_index = text.find("{")
    if start_index == -1:
        raise JSONExtractionError("مفيش '{' في نص الموديل خالص.")

    depth = 0
    in_string = False
    escape_next = False

    for i in range(start_index, len(text)):
        char = text[i]

        if escape_next:
            escape_next = False
            continue

        if char == "\\":
            escape_next = True
            continue

        if char == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start_index : i + 1]

    raise JSONExtractionError(
        "الأقواس مش متوازنة - ممكن الموديل قطع الـ output قبل ما يخلص "
        "(جرب تزود max_new_tokens)."
    )


def extract_json_from_model_output(raw_output: str) -> dict:
    """
    بتاخد النص الخام من الموديل وبترجع dict صحيح.

    Args:
        raw_output: النص الخام اللي رجعه query_model().

    Returns:
        dict مطابق للـ JSON اللي استخرجناه.

    Raises:
        JSONExtractionError: لو تعذر استخراج أو تحليل JSON صحيح.
    """
    if not raw_output or not raw_output.strip():
        raise JSONExtractionError("نص الموديل فاضي.")

    json_str = _find_balanced_json(raw_output)

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        raise JSONExtractionError(
            f"فشل تحليل الـ JSON المستخرج: {e}\nالنص المستخرج: {json_str[:500]}"
        ) from e
        
_FIELD_ALIASES = {
    "experience": {"position": "job_title", "role": "job_title", "title": "job_title"},
    "education": {"year": "graduation_year"},
}

_ALLOWED_FIELDS = {
    "experience": {"job_title", "company", "start_date", "end_date"},
    "education": {"degree", "institution", "graduation_year"},
    "projects": {"name", "description", "technologies_mentioned"},
}


def _derive_graduation_year(item: dict) -> None:
    """
    لو 'graduation_year' مش موجود صراحة، بتحاول تستنتجه من end_date
    (أو start_date لو end_date مش موجود) - المصدر الفعلي اللي الموديل
    بيرجعه غالبًا بدل 'graduation_year' مباشرة.
    """
    if item.get("graduation_year"):
        return

    source = item.get("end_date") or item.get("start_date")
    if not source:
        return

    # ناخد آخر 4 أرقام متتالية في النص (يغطي "Jun 2026", "2016", إلخ)
    import re
    match = re.search(r"(19|20)\d{2}", str(source))
    if match:
        item["graduation_year"] = match.group(0)


def normalize_model_output(raw_cv_data: dict) -> dict:
    for section, allowed in _ALLOWED_FIELDS.items():
        items = raw_cv_data.get(section)
        if not isinstance(items, list):
            continue

        aliases = _FIELD_ALIASES.get(section, {})

        for item in items:
            if not isinstance(item, dict):
                continue

            for old_key, new_key in list(aliases.items()):
                if old_key in item and new_key not in item:
                    item[new_key] = item.pop(old_key)
                elif old_key in item:
                    item.pop(old_key)

            if section == "education":
                _derive_graduation_year(item)

            for key in list(item.keys()):
                if key not in allowed:
                    item.pop(key)

    return raw_cv_data