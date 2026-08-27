"""Embeddings are self-hosted regardless of which text provider is selected.

They run once per document, not once per request, so self-hosting is affordable and
removes a recurring cost. Cached by content hash — re-embedding unchanged text is a bug.
"""
from __future__ import annotations

import hashlib
from functools import lru_cache

from config.settings import get_settings

_CACHE: dict[str, list[float]] = {}


@lru_cache
def _model():
    from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]

    s = get_settings()
    return SentenceTransformer(s.embedding_model, device=s.embedding_device)


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
        vectors = _model().encode([t for _, t in pending], normalize_embeddings=True).tolist()
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