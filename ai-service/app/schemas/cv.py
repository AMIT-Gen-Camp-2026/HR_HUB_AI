from typing import List, Optional
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
    nice_to_have_skills: List[str] = Field(default_factory=list)
    min_experience_years: Optional[int] = None

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


class RankingRequest(StrictModel):
    candidate: CVSchema
    job_description: JobDescription


class RankingResult(StrictModel):
    score: float
    matched_skills: List[str]
    missing_skills: List[str]
    matched_required_skills: List[str] = Field(default_factory=list)
    missing_required_skills: List[str] = Field(default_factory=list)
    matched_preferred_skills: List[str] = Field(default_factory=list)
    missing_preferred_skills: List[str] = Field(default_factory=list)
    semantic_fit: Optional[float] = None
    breakdown: dict