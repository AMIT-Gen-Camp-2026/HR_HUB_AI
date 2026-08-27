from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict


class StrictModel(BaseModel):
    """
    Base class مشتركة لكل الـ sub-models. أي حقل زيادة (زي 'position' بدل
    'job_title') هيتم رفضه صراحة بدل ما يتشال بصمت (extra='ignore' هو
    الافتراضي في Pydantic لو معملناش override ليه).
    """
    model_config = ConfigDict(extra="forbid")


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


# ============================================================
# --- إضافة Sprint 2 (CV-JD Ranking) ---
# ============================================================


class JobDescription(StrictModel):
    title: str
    required_skills: List[str]
    nice_to_have_skills: List[str] = Field(default_factory=list)
    min_experience_years: Optional[int] = None


class RankingRequest(StrictModel):
    candidate: CVSchema
    job_description: JobDescription


class RankingResult(StrictModel):
    score: float
    matched_skills: List[str]
    missing_skills: List[str]
    semantic_fit: Optional[float] = None
    breakdown: dict