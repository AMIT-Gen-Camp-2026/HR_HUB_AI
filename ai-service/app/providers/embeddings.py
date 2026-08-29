"""Embeddings can run locally (sentence-transformers) or through an OpenAI-compatible
API (e.g. Gemini's OpenAI-compatibility endpoint), selected via EMBEDDING_PROVIDER.

They run once per document, not once per request, so cost per call is affordable either
way. Cached by content hash — re-embedding unchanged text is a bug.
"""
from __future__ import annotations

import hashlib
from functools import lru_cache

import httpx

from config.settings import get_settings

_CACHE: dict[str, list[float]] = {}


@lru_cache
def _local_model():
    from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]

    s = get_settings()
    return SentenceTransformer(s.embedding_model, device=s.embedding_device)


def _embed_uncached_api(texts: list[str]) -> list[list[float]]:
    s = get_settings()
    if not s.embedding_api_key:
        raise RuntimeError(
            "GEMINI_API_KEY مش موجود في .env. حط فيه الـ API key بتاعك من Google AI Studio."
        )

    url = f"{s.embedding_api_base_url.rstrip('/')}/embeddings"
    headers = {
        "Authorization": f"Bearer {s.embedding_api_key}",
        "Content-Type": "application/json",
    }
    payload = {"model": s.embedding_api_model, "input": texts}

    with httpx.Client(timeout=30.0) as client:
        try:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            # مهم: نطبع body الرد نفسه - فيه رسالة الخطأ الحقيقية من Gemini
            # (invalid key / invalid model / quota) اللي raise_for_status لوحدها بتبلعها.
            raise RuntimeError(
                f"Embedding API رجع {e.response.status_code}: {e.response.text}"
            ) from e
        data = response.json()

    if "data" not in data:
        raise ValueError(f"Unexpected response format from embedding API: {data}")

    # لازم نرتب حسب "index" - الـ API OpenAI-compatible مش لازم يرجع النتائج
    # بنفس ترتيب الإدخال في كل الحالات (خصوصًا في batch requests)، ولو معملناش
    # sort هنا وحصل عدم تطابق، هيتخلط embedding CV مع embedding JD من غير أي error ظاهر.
    ordered = sorted(data["data"], key=lambda d: d.get("index", 0))
    return [d["embedding"] for d in ordered]


def _embed_uncached(texts: list[str]) -> list[list[float]]:
    s = get_settings()
    if s.embedding_provider == "api":
        return _embed_uncached_api(texts)
    # local (زي ما كان بالظبط)
    return _local_model().encode(texts, normalize_embeddings=True).tolist()


def embed(texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    pending: list[tuple[int, str]] = []
    for i, t in enumerate(texts):
        key = hashlib.sha256(t.encode()).hexdigest()
        if key in _CACHE:
            out.append(_CACHE[key])
        else:
            out.append([])
            pending.append((i, t))
    if pending:
        vectors = _embed_uncached([t for _, t in pending])
        for (i, t), v in zip(pending, vectors, strict=True):
            _CACHE[hashlib.sha256(t.encode()).hexdigest()] = v
            out[i] = v
    return out


# ============================================================
# --- إضافة Sprint 2 (CV-JD Ranking) ---
#
# semantic_fit() هي الدالة اللي ranking.py هيستدعيها - بتبني نص ملخّص
# لكل من الـ CV والـ JD، وتحسب cosine similarity بين الـ embeddings
# بتاعتهم عن طريق embed() اللي فوق.
# ============================================================

from app.schemas.cv import CVSchema, JobDescription  # noqa: E402


def _cv_profile_text(cv: CVSchema) -> str:
    """
    بتبني نص واحد يلخّص الـ CV: skills + inferred_skills + مسميات
    الوظائف (job_title/company) + أسماء ووصف المشاريع.
    """
    parts: list[str] = []

    parts.extend(cv.skills)
    parts.extend(cv.inferred_skills)

    for exp in cv.experience:
        if exp.job_title:
            piece = exp.job_title
            if exp.company:
                piece = f"{piece} at {exp.company}"
            parts.append(piece)

    for proj in cv.projects:
        if proj.name:
            parts.append(proj.name)
        if proj.description:
            parts.append(proj.description)
        parts.extend(proj.technologies_mentioned)

    return ". ".join(p.strip() for p in parts if p and p.strip())


def _jd_text(jd: JobDescription) -> str:
    """JobDescription معندهاش حقل نص حر - بنبني نص تمثيلي من الحقول الموجودة."""
    parts: list[str] = [jd.title]
    parts.extend(jd.required_skills)
    parts.extend(jd.nice_to_have_skills)
    return ". ".join(p.strip() for p in parts if p and p.strip())


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def semantic_fit(cv: CVSchema, jd: JobDescription) -> float:
    """النقطة الوحيدة اللي ranking.py محتاج يستدعيها من الملف ده."""
    cv_text = _cv_profile_text(cv)
    jd_text = _jd_text(jd)

    if not cv_text or not jd_text:
        return 0.0

    cv_vector, jd_vector = embed([cv_text, jd_text])
    return _cosine_similarity(cv_vector, jd_vector)