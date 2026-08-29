"""
app/pipeline/ranking.py
"""

from __future__ import annotations

from app.providers.embeddings import semantic_fit
from app.schemas.cv import CVSchema, JobDescription, RankingResult
from app.skills.canonicalize import canonicalise

REQUIRED_WEIGHT = 0.8
NICE_TO_HAVE_WEIGHT = 0.2

HARD_SKILL_WEIGHT = 0.7
SEMANTIC_WEIGHT = 0.3


def _canonical_set(skill_names: list[str]) -> set[str]:
    ids = (canonicalise(name) for name in skill_names)
    return {i for i in ids if i is not None}


def _match_against_candidate(
    skills: list[str],
    candidate_canonical: set[str],
    candidate_raw_lower: set[str],
) -> tuple[list[str], list[str]]:
    matched: list[str] = []
    missing: list[str] = []

    for skill in skills:
        canon = canonicalise(skill)
        skill_clean = skill.strip().lower()
        
        # Check canonical match OR raw string exact/substring match
        if canon is not None and canon in candidate_canonical:
            matched.append(skill)
        elif any(skill_clean == raw or skill_clean in raw for raw in candidate_raw_lower):
            matched.append(skill)
        else:
            missing.append(skill)

    return matched, missing


def _match_ratio(required: list[str], matched: list[str]) -> float | None:
    if not required:
        return None
    return len(matched) / len(required)


def rank(candidate: CVSchema, job_description: JobDescription) -> RankingResult:
    # 1. تجميع كل المهارات المباشرة والغير مباشرة
    candidate_skill_names = (
        candidate.skills
        + candidate.inferred_skills
        + [tech for project in candidate.projects for tech in project.technologies_mentioned]
        + [exp.job_title for exp in candidate.experience if exp.job_title]
    )
    
    candidate_canonical = _canonical_set(candidate_skill_names)
    candidate_raw_lower = {s.strip().lower() for s in candidate_skill_names if s}

    # 2. مطابقة الـ Skills
    matched_required, missing_required = _match_against_candidate(
        job_description.required_skills, candidate_canonical, candidate_raw_lower
    )
    matched_nice, missing_nice = _match_against_candidate(
        job_description.nice_to_have_skills, candidate_canonical, candidate_raw_lower
    )

    required_ratio = _match_ratio(job_description.required_skills, matched_required)
    nice_ratio = _match_ratio(job_description.nice_to_have_skills, matched_nice)

    weighted_sum = 0.0
    weight_total = 0.0
    if required_ratio is not None:
        weighted_sum += REQUIRED_WEIGHT * required_ratio
        weight_total += REQUIRED_WEIGHT
    if nice_ratio is not None:
        weighted_sum += NICE_TO_HAVE_WEIGHT * nice_ratio
        weight_total += NICE_TO_HAVE_WEIGHT

    hard_skill_score = (weighted_sum / weight_total) if weight_total > 0 else 0.0

    # 3. حساب الـ Semantic Fit (باستخدام Gemini Embedding الشغال ممتاز)
    fit = semantic_fit(candidate, job_description)
    fit_clamped = max(0.0, fit)

    # 4. النتيجة النهائية
    final_score = (HARD_SKILL_WEIGHT * hard_skill_score) + (SEMANTIC_WEIGHT * fit_clamped)

    return RankingResult(
        score=round(final_score * 100, 2),
        matched_skills=matched_required,
        missing_skills=missing_required,
        semantic_fit=round(fit, 4),
        breakdown={
            "required_skills_total": len(job_description.required_skills),
            "required_skills_matched": len(matched_required),
            "required_match_ratio": required_ratio,
            "nice_to_have_skills_total": len(job_description.nice_to_have_skills),
            "nice_to_have_skills_matched": len(matched_nice),
            "nice_to_have_match_ratio": nice_ratio,
            "nice_to_have_matched_skills": matched_nice,
            "nice_to_have_missing_skills": missing_nice,
            "hard_skill_score": round(hard_skill_score, 4),
            "hard_skill_weight": HARD_SKILL_WEIGHT,
            "semantic_fit_raw": round(fit, 4),
            "semantic_fit_clamped": round(fit_clamped, 4),
            "semantic_weight": SEMANTIC_WEIGHT,
        },
    )