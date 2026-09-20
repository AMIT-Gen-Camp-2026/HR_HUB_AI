"""Taxonomy-gated semantic capability ranking."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime

from app.pipeline.jd_enrichment import JDEnrichmentError, extract_jd_requirements
from app.pipeline.redact import assert_clean, redact
from app.pipeline.run import get_cached_ranking, store_cached_ranking
from app.prompts.registry import SEMANTIC_JUDGE_PROMPT_VERSION
from app.providers.judge_provider import (
    JudgeProviderError,
    JudgeResponse,
    query_judge,
    query_semantic_judge,
)
from app.schemas.cv import (
    CVSchema,
    EnrichedRequirement,
    Experience,
    JobDescription,
    RankingResult,
    SkillEvaluation,
)
from app.skills.canonicalize import (
    canonicalise,
    extract_explicit_skills,
    get_encompassed_skills_for_ids,
    get_parent_skills_for_ids,
    is_hierarchy_parent,
)

logger = logging.getLogger(__name__)

REQUIRED_WEIGHT = 0.8
NICE_TO_HAVE_WEIGHT = 0.2
TAXONOMY_VERSION = "2026.09"
JUDGE_PROMPT_VERSION = "ranking-judge-v1"
HARD_SKILL_WEIGHT = 1.0
SEMANTIC_WEIGHT = 0.0

_PRESENT_KEYWORDS: set[str] = {"present", "current", "ongoing", "now"}
_DATE_FORMATS: list[str] = [
    "%m/%Y",
    "%Y-%m",
    "%Y/%m",
    "%B %Y",
    "%b %Y",
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m-%Y",
    "%Y.%m",
]


def _parse_date_string(date_str: str | None, is_end_date: bool = False) -> date | None:
    """Parse an LLM-extracted date string into a datetime.date object.

    Handles MM/YYYY, YYYY-MM, Month YYYY, Mon YYYY, bare 4-digit year YYYY,
    and ongoing role indicators (e.g. 'present', 'current', 'now', 'ongoing').
    """
    if not date_str or not date_str.strip():
        # Policy: Fall back to date.today() when end_date is missing or empty (ongoing role)
        return date.today() if is_end_date else None

    cleaned = date_str.strip()
    if cleaned.casefold() in _PRESENT_KEYWORDS:
        return date.today() if is_end_date else None

    # Strip extraneous punctuation like commas or trailing periods
    cleaned = re.sub(r"[,.]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Check for bare 4-digit year
    if re.fullmatch(r"\d{4}", cleaned):
        try:
            year = int(cleaned)
            if 1900 <= year <= 2100:
                return date(year, 1, 1)
        except ValueError:
            pass

    # Normalize 'Sept' to 'Sep' for %b parsing
    normalized = re.sub(r"\bSept\b", "Sep", cleaned, flags=re.IGNORECASE)

    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            continue

    if is_end_date:
        # Policy: Fall back to date.today() when end_date cannot be parsed
        return date.today()
    return None


def calculate_total_experience_years(experience: list[Experience]) -> float:
    """Calculate the total years of work experience across all candidate roles.

    - Unparseable or missing start dates are skipped (contribute 0.0).
    - Unparseable or missing/ongoing end dates fall back to date.today().
    - Inverted dates (end_date < start_date) contribute 0.0 to prevent corrupting the sum.
    - Overlapping roles are summed as-is without deduplication to support concurrent freelance/part-time roles.
    """
    if not experience:
        return 0.0

    total_years = 0.0
    for entry in experience:
        start = _parse_date_string(entry.start_date, is_end_date=False)
        if start is None:
            continue

        end = _parse_date_string(entry.end_date, is_end_date=True)
        if end is None or end < start:
            # Inverted dates (end < start) or invalid ranges contribute 0.0
            continue

        # Policy: Overlapping roles are summed as-is without deduplication to support concurrent freelance/part-time roles.
        duration = (end - start).days / 365.25
        total_years += duration

    return round(total_years, 2)



def _unique_requirements(requirements: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for requirement in requirements:
        value = requirement.strip()
        if not value:
            continue
        key = canonicalise(value) or value.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(value)
    return unique


def _candidate_evidence(candidate: CVSchema) -> list[str]:
    evidence: list[str] = []
    evidence.extend(f"Explicit skill: {skill}" for skill in candidate.skills if skill)
    evidence.extend(f"Inferred skill: {skill}" for skill in candidate.inferred_skills if skill)
    evidence.extend(
        f"Certification: {certification}"
        for certification in candidate.certifications
        if certification
    )
    for project in candidate.projects:
        if project.name:
            evidence.append(f"Project name: {project.name}")
        if project.description:
            evidence.append(f"Project description: {project.description}")
        evidence.extend(
            f"Project technology: {technology}"
            for technology in project.technologies_mentioned
            if technology
        )
    for experience in candidate.experience:
        parts = [
            value
            for value in (
                experience.job_title,
                experience.company,
                experience.start_date,
                experience.end_date,
                experience.description,
            )
            if value
        ]
        if parts:
            evidence.append("Experience: " + " | ".join(parts))
    return list(dict.fromkeys(evidence))


def _redacted_evidence(candidate: CVSchema) -> list[str]:
    evidence: list[str] = []
    for item in _candidate_evidence(candidate):
        redacted_item, _ = redact(item)
        assert_clean(redacted_item)
        if redacted_item.strip():
            evidence.append(redacted_item.strip())
    return evidence


def _taxonomy_ids(text: str) -> set[str]:
    """Return explicit taxonomy signals only; never use raw containment."""
    ids: set[str] = set()
    direct_id = canonicalise(text)
    if direct_id is not None:
        ids.add(direct_id)
    ids.update(
        canonicalise(term)
        for term in extract_explicit_skills(text)
        if canonicalise(term) is not None
    )
    return ids


def _evidence_for_requirement(
    requirement_skill_ids: set[str],
    evidence: list[str],
    evidence_taxonomy_map: dict[str, set[str]],
) -> list[str]:
    if not evidence:
        return []
    if not requirement_skill_ids:
        return evidence

    return [
        item
        for item in evidence
        if (
            evidence_taxonomy_map.get(item, set()) & requirement_skill_ids
            or get_encompassed_skills_for_ids(evidence_taxonomy_map.get(item, set())) & requirement_skill_ids
        )
    ]


def _judge(
    requirements: list[str], evidence_by_requirement: dict[str, list[str]]
) -> JudgeResponse:
    all_evidence = list(
        dict.fromkeys(
            f"Requirement context: {requirement}\nCandidate evidence excerpt: {item}"
            for requirement, evidence in evidence_by_requirement.items()
            for item in evidence
        )
    )
    judge_requirements = [{"requirement": requirement} for requirement in requirements]
    return query_judge(requirements, all_evidence)


def _zero_evaluation(requirement: str, source_multiplier: float = 0.5) -> SkillEvaluation:
    return SkillEvaluation(
        requirement=requirement,
        satisfaction_percent=0.0,
        reasoning="No recognized candidate-side taxonomy signal was available for this requirement.",
        evidence_quote="",
        source_multiplier=source_multiplier,
        final_skill_score=0.0,
    )


def _average(evaluations: list[SkillEvaluation]) -> float | None:
    if not evaluations:
        return None
    return sum(item.satisfaction_percent for item in evaluations) / (100.0 * len(evaluations))


def _average_final_skill_score(evaluations: list[SkillEvaluation]) -> float | None:
    if not evaluations:
        return None
    return sum(item.final_skill_score for item in evaluations) / (100.0 * len(evaluations))


def _extract_requirement_skill_ids(requirement: str) -> set[str]:
    """Extract canonical taxonomy skill IDs named in the requirement text."""
    direct_id = canonicalise(requirement)
    raw_extracted = [
        canonicalise(skill)
        for skill in extract_explicit_skills(requirement)
        if canonicalise(skill) is not None
    ]
    skill_ids: set[str] = set()
    for cid in raw_extracted:
        if is_hierarchy_parent(cid):
            if direct_id == cid:
                skill_ids.add(cid)
        else:
            skill_ids.add(cid)

    if not skill_ids:
        if direct_id is not None:
            skill_ids.add(direct_id)
    return skill_ids


def _candidate_taxonomy_id_sets(
    candidate: CVSchema,
) -> tuple[set[str], set[str], set[str]]:
    """Build explicit_ids, narrative_ids, and parent_skill_ids sets from candidate structured fields."""
    explicit_ids: set[str] = set()
    for skill in candidate.skills:
        explicit_ids.update(_taxonomy_ids(skill))
    for skill in candidate.inferred_skills:
        explicit_ids.update(_taxonomy_ids(skill))
    for certification in candidate.certifications:
        explicit_ids.update(_taxonomy_ids(certification))

    narrative_ids: set[str] = set()
    for project in candidate.projects:
        if project.name:
            narrative_ids.update(_taxonomy_ids(project.name))
        if project.description:
            narrative_ids.update(_taxonomy_ids(project.description))
        for tech in project.technologies_mentioned:
            if tech:
                narrative_ids.update(_taxonomy_ids(tech))
    for experience in candidate.experience:
        if experience.job_title:
            narrative_ids.update(_taxonomy_ids(experience.job_title))
        if experience.company:
            narrative_ids.update(_taxonomy_ids(experience.company))
        if experience.description:
            narrative_ids.update(_taxonomy_ids(experience.description))

    parent_skill_ids = get_encompassed_skills_for_ids(explicit_ids)

    return explicit_ids, narrative_ids, parent_skill_ids


def _calculate_source_multiplier(
    requirement: str,
    explicit_ids: set[str],
    narrative_ids: set[str],
    parent_skill_ids: set[str],
    requirement_skill_ids: set[str] | None = None,
) -> float:
    if requirement_skill_ids is None:
        requirement_skill_ids = _extract_requirement_skill_ids(requirement)

    if not requirement_skill_ids:
        # Taxonomy-unresolvable requirement: default conservatively to 0.5
        return 0.5

    if requirement_skill_ids & explicit_ids:
        return 1.0

    if requirement_skill_ids & parent_skill_ids:
        return 0.80

    if requirement_skill_ids & narrative_ids:
        return 0.5

    # Requirement taxonomy IDs not found in candidate explicit, parent-encompassed,
    # or narrative signals; default to conservative 0.5 multiplier.
    return 0.5


def _rank_taxonomy(
    candidate: CVSchema, job_description: JobDescription
) -> RankingResult:
    required = _unique_requirements(job_description.required_skills)
    skill_groups: list[list[str]] = (
        [_unique_requirements(group) for group in job_description.required_skill_groups]
        if job_description.required_skill_groups
        else []
    )
    grouped_requirements: list[str] = [req for group in skill_groups for req in group]
    preferred = _unique_requirements(job_description.nice_to_have_skills)
    all_requirements = required + grouped_requirements + preferred
    evidence = _redacted_evidence(candidate)

    explicit_ids, narrative_ids, parent_skill_ids = _candidate_taxonomy_id_sets(candidate)

    evidence_taxonomy_map: dict[str, set[str]] = {
        item: _taxonomy_ids(item) for item in evidence
    }

    evidence_by_requirement: dict[str, list[str]] = {}
    skipped: dict[str, SkillEvaluation] = {}
    judgeable: list[str] = []
    for requirement in all_requirements:
        requirement_skill_ids = _extract_requirement_skill_ids(requirement)
        relevant = _evidence_for_requirement(
            requirement_skill_ids, evidence, evidence_taxonomy_map
        )
        multiplier = _calculate_source_multiplier(
            requirement, explicit_ids, narrative_ids, parent_skill_ids, requirement_skill_ids
        )
        if relevant:
            evidence_by_requirement[requirement] = relevant
            judgeable.append(requirement)
        else:
            skipped[requirement] = _zero_evaluation(requirement, source_multiplier=multiplier)

    judged_response = _judge(judgeable, evidence_by_requirement) if judgeable else None
    judged = judged_response.evaluations if judged_response else []
    judged_by_requirement = {item.requirement: item for item in judged}

    def _build_evaluation(requirement: str) -> SkillEvaluation:
        multiplier = _calculate_source_multiplier(
            requirement, explicit_ids, narrative_ids, parent_skill_ids
        )
        if requirement in judged_by_requirement:
            item = judged_by_requirement[requirement]
            final_skill_score = round(item.satisfaction_percent * multiplier, 2)
            return SkillEvaluation(
                requirement=item.requirement,
                satisfaction_percent=item.satisfaction_percent,
                reasoning=item.reasoning,
                evidence_quote=item.evidence_quote,
                source_multiplier=multiplier,
                final_skill_score=final_skill_score,
                skill_group_id=None,
                is_group_representative=False,
            )
        else:
            return skipped[requirement]

    required_evaluations: list[SkillEvaluation] = [
        _build_evaluation(req) for req in required
    ]

    group_evaluations: list[SkillEvaluation] = []
    group_representative_evaluations: list[SkillEvaluation] = []
    for group_id, group_reqs in enumerate(skill_groups):
        members = [_build_evaluation(req) for req in group_reqs]
        best_member = max(members, key=lambda m: m.final_skill_score)
        for member in members:
            is_rep = member is best_member
            annotated = SkillEvaluation(
                requirement=member.requirement,
                satisfaction_percent=member.satisfaction_percent,
                reasoning=member.reasoning,
                evidence_quote=member.evidence_quote,
                source_multiplier=member.source_multiplier,
                final_skill_score=member.final_skill_score,
                skill_group_id=group_id,
                is_group_representative=is_rep,
            )
            group_evaluations.append(annotated)
            if is_rep:
                group_representative_evaluations.append(annotated)

    preferred_evaluations: list[SkillEvaluation] = [
        _build_evaluation(req) for req in preferred
    ]

    evaluations: list[SkillEvaluation] = (
        required_evaluations + group_evaluations + preferred_evaluations
    )
    effective_required_evaluations = (
        required_evaluations + group_representative_evaluations
    )

    # Legacy ratios preserved for breakdown dictionary compatibility
    required_ratio = _average(effective_required_evaluations)
    nice_ratio = _average(preferred_evaluations)
    if required_ratio is not None:
        preferred_bonus = NICE_TO_HAVE_WEIGHT * (nice_ratio or 0.0) * (1.0 - required_ratio)
        hard_skill_score = required_ratio + preferred_bonus
    else:
        preferred_bonus = 0.0
        hard_skill_score = NICE_TO_HAVE_WEIGHT * (nice_ratio or 0.0)

    # 70/20/10 Scoring Formula:
    # 1. Required skills component (70%): average final_skill_score / 100 * 0.70
    req_final_avg = _average_final_skill_score(effective_required_evaluations)
    required_component = (req_final_avg or 0.0) * 0.70

    # 2. Nice-to-have skills component (20%): average final_skill_score / 100 * 0.20
    pref_final_avg = _average_final_skill_score(preferred_evaluations)
    nice_to_have_component = (pref_final_avg or 0.0) * 0.20

    # 3. Experience duration component (10%): ratio capped at 1.0 * 0.10
    candidate_total_years = calculate_total_experience_years(candidate.experience)
    min_exp = job_description.min_experience_years
    if min_exp is None or min_exp <= 0:
        experience_ratio = 1.0
    else:
        experience_ratio = min(candidate_total_years / float(min_exp), 1.0)
    experience_component = experience_ratio * 0.10

    final_score = required_component + nice_to_have_component + experience_component
    return RankingResult(
        score=round(final_score * 100, 2),
        matched_skills=[],
        missing_skills=[],
        matched_required_skills=[],
        missing_required_skills=[],
        matched_preferred_skills=[],
        missing_preferred_skills=[],
        semantic_fit=None,
        judge_provider=judged_response.provider if judged_response else None,
        judge_model=judged_response.model if judged_response else None,
        skill_evaluations=evaluations,
        breakdown={
            "required_skills_total": len(required) + len(skill_groups),
            "required_satisfaction_average": required_ratio,
            "nice_to_have_skills_total": len(preferred),
            "nice_to_have_satisfaction_average": nice_ratio,
            "preferred_bonus": round(preferred_bonus, 4),
            "hard_skill_score": round(hard_skill_score, 4),
            "hard_skill_weight": HARD_SKILL_WEIGHT,
            "semantic_weight": SEMANTIC_WEIGHT,
            "taxonomy_version": TAXONOMY_VERSION,
            "judge_prompt_version": JUDGE_PROMPT_VERSION,
            "scoring_version": "weighted-70-20-10-v1",
            "fallback_to_taxonomy": False,
            "required_component": round(required_component, 4),
            "nice_to_have_component": round(nice_to_have_component, 4),
            "experience_component": round(experience_component, 4),
            "candidate_total_years": candidate_total_years,
            "experience_ratio": round(experience_ratio, 4),
        },
    )


def _rank_semantic(
    candidate: CVSchema, job_description: JobDescription
) -> RankingResult:
    enriched_jd = extract_jd_requirements(job_description)
    evidence = _redacted_evidence(candidate)

    enriched_required = enriched_jd.required_skills
    enriched_groups = enriched_jd.required_skill_groups or []
    grouped_enriched = [req for group in enriched_groups for req in group]
    enriched_preferred = enriched_jd.nice_to_have_skills
    all_enriched = enriched_required + grouped_enriched + enriched_preferred

    judged_response = (
        query_semantic_judge(all_enriched, evidence) if all_enriched else None
    )
    judged = judged_response.evaluations if judged_response else []
    judged_by_requirement = {item.requirement: item for item in judged}

    def _build_semantic_evaluation(req: EnrichedRequirement) -> SkillEvaluation:
        if req.raw_text in judged_by_requirement:
            item = judged_by_requirement[req.raw_text]
            sat = item.satisfaction_percent
            reasoning = item.reasoning
            quote = item.evidence_quote
        else:
            sat = 0.0
            reasoning = "No recognized candidate evidence available."
            quote = ""

        # Unconditional source_multiplier = 1.0 in semantic mode
        final_skill_score = round(sat * 1.0, 2)
        return SkillEvaluation(
            requirement=req.raw_text,
            satisfaction_percent=sat,
            reasoning=reasoning,
            evidence_quote=quote,
            source_multiplier=1.0,
            final_skill_score=final_skill_score,
            skill_group_id=None,
            is_group_representative=False,
        )

    required_evaluations: list[SkillEvaluation] = [
        _build_semantic_evaluation(req) for req in enriched_required
    ]

    group_evaluations: list[SkillEvaluation] = []
    group_representative_evaluations: list[SkillEvaluation] = []
    for group_id, group_reqs in enumerate(enriched_groups):
        members = [_build_semantic_evaluation(req) for req in group_reqs]
        best_member = max(members, key=lambda m: m.final_skill_score)
        for member in members:
            is_rep = member is best_member
            annotated = SkillEvaluation(
                requirement=member.requirement,
                satisfaction_percent=member.satisfaction_percent,
                reasoning=member.reasoning,
                evidence_quote=member.evidence_quote,
                source_multiplier=1.0,
                final_skill_score=member.final_skill_score,
                skill_group_id=group_id,
                is_group_representative=is_rep,
            )
            group_evaluations.append(annotated)
            if is_rep:
                group_representative_evaluations.append(annotated)

    preferred_evaluations: list[SkillEvaluation] = [
        _build_semantic_evaluation(req) for req in enriched_preferred
    ]

    evaluations: list[SkillEvaluation] = (
        required_evaluations + group_evaluations + preferred_evaluations
    )
    effective_required_evaluations = (
        required_evaluations + group_representative_evaluations
    )

    required_ratio = _average(effective_required_evaluations)
    nice_ratio = _average(preferred_evaluations)
    if required_ratio is not None:
        preferred_bonus = NICE_TO_HAVE_WEIGHT * (nice_ratio or 0.0) * (1.0 - required_ratio)
        hard_skill_score = required_ratio + preferred_bonus
    else:
        preferred_bonus = 0.0
        hard_skill_score = NICE_TO_HAVE_WEIGHT * (nice_ratio or 0.0)

    # 70/20/10 Scoring Formula:
    # 1. Required skills component (70%): average final_skill_score / 100 * 0.70
    req_final_avg = _average_final_skill_score(effective_required_evaluations)
    required_component = (req_final_avg or 0.0) * 0.70

    # 2. Nice-to-have skills component (20%): average final_skill_score / 100 * 0.20
    pref_final_avg = _average_final_skill_score(preferred_evaluations)
    nice_to_have_component = (pref_final_avg or 0.0) * 0.20

    # 3. Experience duration component (10%): ratio capped at 1.0 * 0.10
    candidate_total_years = calculate_total_experience_years(candidate.experience)
    min_exp = job_description.min_experience_years
    if min_exp is None or min_exp <= 0:
        experience_ratio = 1.0
    else:
        experience_ratio = min(candidate_total_years / float(min_exp), 1.0)
    experience_component = experience_ratio * 0.10

    final_score = required_component + nice_to_have_component + experience_component
    return RankingResult(
        score=round(final_score * 100, 2),
        matched_skills=[],
        missing_skills=[],
        matched_required_skills=[],
        missing_required_skills=[],
        matched_preferred_skills=[],
        missing_preferred_skills=[],
        semantic_fit=None,
        judge_provider=judged_response.provider if judged_response else None,
        judge_model=judged_response.model if judged_response else None,
        skill_evaluations=evaluations,
        breakdown={
            "required_skills_total": len(enriched_required) + len(enriched_groups),
            "required_satisfaction_average": required_ratio,
            "nice_to_have_skills_total": len(enriched_preferred),
            "nice_to_have_satisfaction_average": nice_ratio,
            "preferred_bonus": round(preferred_bonus, 4),
            "hard_skill_score": round(hard_skill_score, 4),
            "hard_skill_weight": HARD_SKILL_WEIGHT,
            "semantic_weight": SEMANTIC_WEIGHT,
            "taxonomy_version": None,
            "judge_prompt_version": SEMANTIC_JUDGE_PROMPT_VERSION,
            "scoring_version": "weighted-70-20-10-v1",
            "fallback_to_taxonomy": False,
            "required_component": round(required_component, 4),
            "nice_to_have_component": round(nice_to_have_component, 4),
            "experience_component": round(experience_component, 4),
            "candidate_total_years": candidate_total_years,
            "experience_ratio": round(experience_ratio, 4),
        },
    )


def rank(candidate: CVSchema, job_description: JobDescription) -> RankingResult:
    cached = get_cached_ranking(candidate, job_description)
    if cached is not None:
        return cached

    mode = getattr(job_description, "matching_mode", "taxonomy")
    if mode == "semantic":
        try:
            result = _rank_semantic(candidate, job_description)
            store_cached_ranking(candidate, job_description, result)
            return result
        except Exception as error:
            logger.warning(
                "Semantic matching failed (%s: %s); transparently falling back to taxonomy matching.",
                type(error).__name__,
                error,
            )
            result = _rank_taxonomy(candidate, job_description)
            result.breakdown["fallback_to_taxonomy"] = True
            store_cached_ranking(candidate, job_description, result)
            return result

    result = _rank_taxonomy(candidate, job_description)
    store_cached_ranking(candidate, job_description, result)
    return result
