"""
app/pipeline/ranking.py

الملف الأساسي لحساب score التوافق بين CV وJD - خوارزمية deterministic
(skill set match + weights)، مفيش أي LLM call هنا خالص.
"""

from __future__ import annotations

from app.providers.embeddings import semantic_fit
from app.schemas.cv import CVSchema, JobDescription, RankingResult
from app.skills.canonicalize import canonicalise

# وزن أعلى لـ required_skills من nice_to_have_skills داخل hard_skill_score
# نفسه. القيم دي تقديرية مني - محتاجة تأكيد/تعديل منك.
REQUIRED_WEIGHT = 0.8
NICE_TO_HAVE_WEIGHT = 0.2

# دمج hard_skill_score مع semantic_fit - final_score =
# 0.7 × hard_skill_score + 0.3 × semantic_fit، زي ما اتفقنا بالظبط.
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
    """
    بترجع (matched, missing) - أسماء الـ skills الأصلية زي ما اتكتبت
    في الـ JD. كل skill بيتقارن: عن طريق canonical id لو معروف في
    الـ taxonomy، أو fallback نصي حرفي (case-insensitive) لو مش معروف
    (canonicalise() رجعت None) - عشان skill غير معروف للـ taxonomy
    ميتحسبش missing ظلمًا لو موجود بنفس الاسم بالظبط في الـ CV.
    """
    matched: list[str] = []
    missing: list[str] = []

    for skill in skills:
        canon = canonicalise(skill)
        if canon is not None and canon in candidate_canonical:
            matched.append(skill)
        elif canon is None and skill.strip().lower() in candidate_raw_lower:
            matched.append(skill)
        else:
            missing.append(skill)

    return matched, missing


def _match_ratio(required: list[str], matched: list[str]) -> float | None:
    if not required:
        return None
    return len(matched) / len(required)


def rank(candidate: CVSchema, job_description: JobDescription) -> RankingResult:
    """
    ملحوظة: min_experience_years في JobDescription مش مستخدم في الحساب
    ده حاليًا - CVSchema.Experience معندهاش تاريخ منظم يسهّل حساب
    إجمالي سنين الخبرة منه.
    """
    candidate_skill_names = (
        candidate.skills
        + candidate.inferred_skills
        + [tech for project in candidate.projects for tech in project.technologies_mentioned]
    )
    candidate_canonical = _canonical_set(candidate_skill_names)
    candidate_raw_lower = {s.strip().lower() for s in candidate_skill_names}

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

    fit = semantic_fit(candidate, job_description)
    fit_clamped = max(0.0, fit)

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