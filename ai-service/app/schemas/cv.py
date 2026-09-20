from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """
    يتجاهل أي حقول زيادة راجعة من الـ LLM بصمت لتجنب الـ Validation Error.
    """
    model_config = ConfigDict(extra="ignore")


class PersonalInfo(StrictModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None


class Education(StrictModel):
    degree: Optional[str] = None
    institution: Optional[str] = None
    graduation_year: Optional[str] = None


class Experience(StrictModel):
    job_title: Optional[str] = None
    company: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    description: Optional[str] = None


class Project(StrictModel):
    name: Optional[str] = None
    description: Optional[str] = None
    technologies_mentioned: List[str] = Field(default_factory=list)


class CVSchema(StrictModel):
    personal_info: PersonalInfo = Field(default_factory=PersonalInfo)
    education: List[Education] = Field(default_factory=list)
    experience: List[Experience] = Field(default_factory=list)
    projects: List[Project] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    inferred_skills: List[str] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)


EMPTY_CV_SCHEMA: dict = CVSchema().model_dump()


class JobDescription(StrictModel):
    title: str
    required_skills: List[str]
    required_skill_groups: list[list[str]] | None = None
    nice_to_have_skills: List[str] = Field(default_factory=list)
    min_experience_years: Optional[int] = None
    matching_mode: Literal["taxonomy", "semantic"] = "taxonomy"

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_payload(cls, value):
        if not isinstance(value, dict):
            return value

        normalized = dict(value)
        if "title" not in normalized and "job_title" in normalized:
            normalized["title"] = normalized["job_title"]

        required = normalized.get("required_skills")
        if isinstance(required, dict):
            normalized["required_skills"] = [
                skill
                for skills in required.values()
                if isinstance(skills, list)
                for skill in skills
            ]

        if "nice_to_have_skills" not in normalized:
            qualifications = normalized.get("preferred_qualifications", [])
            if isinstance(qualifications, list):
                normalized["nice_to_have_skills"] = qualifications

        return normalized

    @model_validator(mode="after")
    def validate_skill_groups(self) -> "JobDescription":
        if self.required_skill_groups is not None:
            for group in self.required_skill_groups:
                if len(group) < 2:
                    raise ValueError(
                        f"Each group in required_skill_groups must contain at least 2 skills, got {len(group)}: {group}"
                    )

            req_skills_map = {s.strip().lower(): s for s in self.required_skills}
            for group in self.required_skill_groups:
                for skill in group:
                    cleaned = skill.strip().lower()
                    if cleaned in req_skills_map:
                        conflicting_name = req_skills_map[cleaned]
                        raise ValueError(
                            f"Skill '{conflicting_name}' cannot be listed as both an independent requirement and part of an alternative group."
                        )
        return self


class RankingRequest(StrictModel):
    candidate: CVSchema
    job_description: JobDescription


class SkillEvaluation(StrictModel):
    requirement: str
    satisfaction_percent: float = Field(ge=0.0, le=100.0)
    reasoning: str
    evidence_quote: str
    source_multiplier: float = Field(default=1.0, ge=0.0, le=1.0)
    final_skill_score: float = Field(default=0.0, ge=0.0, le=100.0)
    skill_group_id: int | None = None
    is_group_representative: bool = False


class RankingResult(StrictModel):
    score: float
    matched_skills: List[str] = Field(default_factory=list)
    missing_skills: List[str] = Field(default_factory=list)
    matched_required_skills: List[str] = Field(default_factory=list)
    missing_required_skills: List[str] = Field(default_factory=list)
    matched_preferred_skills: List[str] = Field(default_factory=list)
    missing_preferred_skills: List[str] = Field(default_factory=list)
    semantic_fit: Optional[float] = None
    judge_provider: Optional[str] = None
    judge_model: Optional[str] = None
    skill_evaluations: List[SkillEvaluation] = Field(default_factory=list)
    breakdown: dict


class EnrichedRequirement(StrictModel):
    raw_text: str
    core_intent: str
    implied_components: List[str] = Field(default_factory=list)
    is_composite: bool = False
    specificity: Literal["specific", "vague"] = "specific"


class EnrichedJobDescription(StrictModel):
    job_description: JobDescription
    required_skills: List[EnrichedRequirement] = Field(default_factory=list)
    required_skill_groups: list[list[EnrichedRequirement]] | None = None
    nice_to_have_skills: List[EnrichedRequirement] = Field(default_factory=list)