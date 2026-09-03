"""
app/pipeline/ranking.py
"""

from __future__ import annotations

from app.providers.embeddings import semantic_fit
from app.schemas.cv import CVSchema, JobDescription, RankingResult
from app.skills.canonicalize import canonicalise

REQUIRED_WEIGHT = 0.8
NICE_TO_HAVE_WEIGHT = 0.2
TAXONOMY_VERSION = "2026.09"

# Exact/canonical evidence is authoritative. Semantic fit remains available as
# context, but an external provider must not alter the reproducible score.
HARD_SKILL_WEIGHT = 1.0
SEMANTIC_WEIGHT = 0.0


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
        elif any(
            skill_clean == raw
            or (len(skill_clean) >= 4 and skill_clean in raw)
            or (len(raw) >= 4 and raw in skill_clean)
            for raw in candidate_raw_lower
        ):
            matched.append(skill)
        else:
            missing.append(skill)

    return matched, missing


def _match_ratio(required: list[str], matched: list[str]) -> float | None:
    if not required:
        return None
    return len(matched) / len(required)


def _unique_skills(skills: list[str]) -> list[str]:
    """Deduplicate equivalent display values while preserving JD order."""
    unique: list[str] = []
    seen: set[str] = set()
    for skill in skills:
        key = canonicalise(skill) or skill.strip().casefold()
        if key and key not in seen:
            seen.add(key)
            unique.append(skill)
    return unique


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

    required_skills = _unique_skills(job_description.required_skills)
    preferred_skills = _unique_skills(job_description.nice_to_have_skills)

    # 2. مطابقة الـ Skills
    matched_required, missing_required = _match_against_candidate(
        required_skills, candidate_canonical, candidate_raw_lower
    )
    matched_nice, missing_nice = _match_against_candidate(
        preferred_skills, candidate_canonical, candidate_raw_lower
    )

    required_ratio = _match_ratio(required_skills, matched_required)
    nice_ratio = _match_ratio(preferred_skills, matched_nice)

    if required_ratio is not None:
        preferred_bonus = NICE_TO_HAVE_WEIGHT * (nice_ratio or 0.0) * (
            1.0 - required_ratio
        )
        hard_skill_score = required_ratio + preferred_bonus
    else:
        # With no required skills, preferred evidence is useful but capped at 20.
        hard_skill_score = NICE_TO_HAVE_WEIGHT * (nice_ratio or 0.0)

    # 3. حساب الـ Semantic Fit (باستخدام Gemini Embedding الشغال ممتاز)
    fit = semantic_fit(candidate, job_description) if SEMANTIC_WEIGHT else 0.0
    fit_clamped = max(0.0, min(1.0, fit))

    # 4. النتيجة النهائية
    final_score = (HARD_SKILL_WEIGHT * hard_skill_score) + (SEMANTIC_WEIGHT * fit_clamped)

    return RankingResult(
        score=round(final_score * 100, 2),
        matched_skills=matched_required,
        missing_skills=missing_required,
        matched_required_skills=matched_required,
        missing_required_skills=missing_required,
        matched_preferred_skills=matched_nice,
        missing_preferred_skills=missing_nice,
        semantic_fit=round(fit, 4),
        breakdown={
            "required_skills_total": len(required_skills),
            "required_skills_matched": len(matched_required),
            "required_match_ratio": required_ratio,
            "nice_to_have_skills_total": len(preferred_skills),
            "nice_to_have_skills_matched": len(matched_nice),
            "nice_to_have_match_ratio": nice_ratio,
            "nice_to_have_matched_skills": matched_nice,
            "nice_to_have_missing_skills": missing_nice,
            "hard_skill_score": round(hard_skill_score, 4),
            "hard_skill_weight": HARD_SKILL_WEIGHT,
            "semantic_fit_raw": round(fit, 4),
            "semantic_fit_clamped": round(fit_clamped, 4),
            "semantic_weight": SEMANTIC_WEIGHT,
            "taxonomy_version": TAXONOMY_VERSION,
            "scoring_version": "deterministic-hard-skills-v2",
        },
    )