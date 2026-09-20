# Codebase Audit & State Report: AI-Service

**Repository Root:** `d:\github project\HR_HUB_AI`  
**Target Service:** `ai-service`  
**Audit Timestamp:** 2026-09-13  
**Audit Scope:** Read-only verification of scoring engine, evaluation pipeline, schemas, security safeguards, configuration, and test suites.

---

## Executive Summary

This audit report establishes the comprehensive baseline of the `ai-service` repository in its current state. The service is a Flask-based REST API designed to evaluate and rank candidate CVs (PDF/DOCX) against Job Descriptions (JDs) using a multi-provider LLM capability judge (Gemini -> Groq -> OpenRouter), canonical skill taxonomy matching, snapshot caching, and PII redaction safeguards.

---

## 1. Full Source of Core Files (Verbatim & Complete)

### 1.1 `ai-service/app/pipeline/ranking.py`
```python
"""Taxonomy-gated semantic capability ranking."""

from __future__ import annotations

from app.providers.judge_provider import JudgeResponse, query_judge
from app.pipeline.redact import assert_clean, redact
from app.pipeline.run import get_cached_ranking, store_cached_ranking
from app.schemas.cv import CVSchema, JobDescription, RankingResult, SkillEvaluation
from app.skills.canonicalize import canonicalise, extract_explicit_skills

REQUIRED_WEIGHT = 0.8
NICE_TO_HAVE_WEIGHT = 0.2
TAXONOMY_VERSION = "2026.09"
JUDGE_PROMPT_VERSION = "ranking-judge-v1"
HARD_SKILL_WEIGHT = 1.0
SEMANTIC_WEIGHT = 0.0


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


def _evidence_for_requirement(requirement: str, evidence: list[str]) -> list[str]:
    # Taxonomy overlap is useful context, but it must not hard-block semantic
    # evaluation when the candidate has broader or differently phrased evidence.
    # Only an entirely empty candidate should be skipped before the judge.
    if not evidence:
        return []
    return evidence


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


def _zero_evaluation(requirement: str) -> SkillEvaluation:
    return SkillEvaluation(
        requirement=requirement,
        satisfaction_percent=0.0,
        reasoning="No recognized candidate-side taxonomy signal was available for this requirement.",
        evidence_quote="",
    )


def _average(evaluations: list[SkillEvaluation]) -> float | None:
    if not evaluations:
        return None
    return sum(item.satisfaction_percent for item in evaluations) / (100.0 * len(evaluations))


def rank(candidate: CVSchema, job_description: JobDescription) -> RankingResult:
    cached = get_cached_ranking(candidate, job_description)
    if cached is not None:
        return cached

    required = _unique_requirements(job_description.required_skills)
    preferred = _unique_requirements(job_description.nice_to_have_skills)
    all_requirements = required + preferred
    evidence = _redacted_evidence(candidate)

    evidence_by_requirement: dict[str, list[str]] = {}
    skipped: dict[str, SkillEvaluation] = {}
    judgeable: list[str] = []
    for requirement in all_requirements:
        relevant = _evidence_for_requirement(requirement, evidence)
        if relevant:
            evidence_by_requirement[requirement] = relevant
            judgeable.append(requirement)
        else:
            skipped[requirement] = _zero_evaluation(requirement)

    judged_response = _judge(judgeable, evidence_by_requirement) if judgeable else None
    judged = judged_response.evaluations if judged_response else []
    judged_by_requirement = {item.requirement: item for item in judged}
    evaluations = [
        judged_by_requirement[requirement]
        if requirement in judged_by_requirement
        else skipped[requirement]
        for requirement in all_requirements
    ]
    required_evaluations = evaluations[: len(required)]
    preferred_evaluations = evaluations[len(required) :]

    required_ratio = _average(required_evaluations)
    nice_ratio = _average(preferred_evaluations)
    if required_ratio is not None:
        preferred_bonus = NICE_TO_HAVE_WEIGHT * (nice_ratio or 0.0) * (1.0 - required_ratio)
        hard_skill_score = required_ratio + preferred_bonus
    else:
        preferred_bonus = 0.0
        hard_skill_score = NICE_TO_HAVE_WEIGHT * (nice_ratio or 0.0)

    final_score = HARD_SKILL_WEIGHT * hard_skill_score
    result = RankingResult(
        score=round(final_score * 100, 2),
        # These legacy fields are deliberately empty. skill_evaluations is the
        # authoritative structured contract and avoids presenting JD text as CV fact.
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
            "required_skills_total": len(required),
            "required_satisfaction_average": required_ratio,
            "nice_to_have_skills_total": len(preferred),
            "nice_to_have_satisfaction_average": nice_ratio,
            "preferred_bonus": round(preferred_bonus, 4),
            "hard_skill_score": round(hard_skill_score, 4),
            "hard_skill_weight": HARD_SKILL_WEIGHT,
            "semantic_weight": SEMANTIC_WEIGHT,
            "taxonomy_version": TAXONOMY_VERSION,
            "judge_prompt_version": JUDGE_PROMPT_VERSION,
            "scoring_version": "llm-capability-judge-v1",
        },
    )
    store_cached_ranking(candidate, job_description, result)
    return result
```

---

### 1.2 `ai-service/app/providers/judge_provider.py`
```python
"""Provider-neutral multi-provider LLM capability judge."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.pipeline.postprocess import extract_json_from_model_output
from app.pipeline.redact import assert_clean
from app.prompts.registry import build_judge_prompt
from app.schemas.cv import SkillEvaluation
from config.settings import config

logger = logging.getLogger(__name__)


class JudgeProviderError(Exception):
    pass


@dataclass(frozen=True)
class JudgeResponse:
    evaluations: list[SkillEvaluation]
    provider: str
    model: str


class JudgeProvider:
    name: str
    model: str

    def evaluate(
        self, requirements: list[str], evidence: list[str]
    ) -> JudgeResponse:
        raise NotImplementedError

    def _messages(self, requirements: list[str], evidence: list[str]) -> tuple[str, str]:
        return build_judge_prompt(
            [{"requirement": requirement} for requirement in requirements], evidence
        )

    @staticmethod
    def _parse(
        raw_content: str, requirements: list[str], evidence: list[str]
    ) -> list[SkillEvaluation]:
        payload = extract_json_from_model_output(raw_content)
        items = payload.get("evaluations")
        if not isinstance(items, list) or len(items) != len(requirements):
            raise JudgeProviderError("Judge returned an unexpected evaluation count")
        evaluations = [SkillEvaluation(**item) for item in items]
        for evaluation, requirement in zip(evaluations, requirements, strict=True):
            if evaluation.requirement != requirement:
                raise JudgeProviderError("Judge requirement order/content mismatch")
            if evaluation.evidence_quote:
                normalized_quote = " ".join(evaluation.evidence_quote.split())
                if not any(normalized_quote in " ".join(item.split()) for item in evidence):
                    raise JudgeProviderError("Judge evidence_quote is not candidate evidence")
        return evaluations


class OpenAICompatibleJudgeProvider(JudgeProvider):
    def __init__(
        self,
        name: str,
        model: str,
        api_key: str,
        base_url: str,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._extra_headers = extra_headers or {}

    def evaluate(self, requirements: list[str], evidence: list[str]) -> JudgeResponse:
        system_prompt, user_prompt = self._messages(requirements, evidence)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            **self._extra_headers,
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }
        try:
            with httpx.Client(timeout=config.JUDGE_TIMEOUT_SECONDS) as client:
                response = client.post(
                    f"{self._base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                body = response.json()
                content = body["choices"][0]["message"]["content"]
            evaluations = self._parse(content, requirements, evidence)
            return JudgeResponse(evaluations, self.name, self.model)
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            raise JudgeProviderError(f"{self.name}/{self.model}: {error}") from error


class GeminiJudgeProvider(JudgeProvider):
    GEMINI_503_RETRY_DELAYS = (1, 2, 4)
    GEMINI_2_5_FLASH_CANDIDATES = (
        "gemini-3.8-flash",
        "gemini-3.7-flash",
        "gemini-3.5-flash-lite",
    )

    def __init__(self, api_key: str, model: str) -> None:
        self.name = "gemini"
        self.model = self._normalize_model(model)
        self._api_key = api_key

    @classmethod
    def _normalize_model(cls, model: str) -> str:
        candidate = (model or "").strip()
        if not candidate:
            return "gemini-3.8-flash"
        aliases = {
            "gemini-2.5-flash": "gemini-3.8-flash",
            "gemini-2.5-flash-latest": "gemini-3.8-flash",
            "gemini-2.5-flash-preview": "gemini-3.8-flash",
            "gemini-2.5-flash-preview-09-2025": "gemini-3.8-flash",
            "gemini-flash-latest": "gemini-3.8-flash",
        }
        return aliases.get(candidate, candidate)

    def evaluate(self, requirements: list[str], evidence: list[str]) -> JudgeResponse:
        system_prompt, user_prompt = self._messages(requirements, evidence)
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": 0.0,
                "responseMimeType": "application/json",
            },
        }

        candidate_models: list[str] = []
        seen: set[str] = set()
        for model_name in [self.model, *self.GEMINI_2_5_FLASH_CANDIDATES]:
            if model_name and model_name not in seen:
                candidate_models.append(model_name)
                seen.add(model_name)

        last_error: Exception | None = None
        for model_name in candidate_models:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model_name}:generateContent"
            )
            try:
                with httpx.Client(timeout=config.JUDGE_TIMEOUT_SECONDS) as client:
                    for attempt in range(len(self.GEMINI_503_RETRY_DELAYS) + 1):
                        response = client.post(
                            url,
                            headers={"x-goog-api-key": self._api_key},
                            json=payload,
                        )
                        if response.status_code != 503:
                            break
                        if attempt == len(self.GEMINI_503_RETRY_DELAYS):
                            response.raise_for_status()
                        delay = self.GEMINI_503_RETRY_DELAYS[attempt]
                        logger.warning(
                            "Gemini judge returned 503, retrying model=%s in %ss",
                            model_name,
                            delay,
                        )
                        time.sleep(delay)
                    if response.status_code == 404:
                        logger.warning(
                            "Gemini model not found for judge, retrying with alternative model: %s",
                            model_name,
                        )
                        last_error = httpx.HTTPStatusError(
                            f"404 for model {model_name}",
                            request=response.request,
                            response=response,
                        )
                        continue
                    response.raise_for_status()
                    body = response.json()
                    content = body["candidates"][0]["content"]["parts"][0]["text"]
                evaluations = self._parse(content, requirements, evidence)
                return JudgeResponse(evaluations, self.name, model_name)
            except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
                last_error = error
                if isinstance(error, httpx.HTTPStatusError) and error.response is not None and error.response.status_code == 404:
                    continue
                raise JudgeProviderError(f"{self.name}/{model_name}: {error}") from error

        if last_error is not None:
            raise JudgeProviderError(f"{self.name}/{self.model}: {last_error}") from last_error
        raise JudgeProviderError(f"{self.name}/{self.model}: Gemini judge request failed")


def configured_judge_chain() -> list[JudgeProvider]:
    providers: list[JudgeProvider] = []
    if config.GEMINI_API_KEY:
        providers.append(GeminiJudgeProvider(config.GEMINI_API_KEY, config.GEMINI_JUDGE_MODEL))
    if config.GROQ_API_KEY:
        providers.append(
            OpenAICompatibleJudgeProvider(
                "groq",
                config.GROQ_JUDGE_MODEL,
                config.GROQ_API_KEY,
                config.GROQ_BASE_URL,
            )
        )
    if config.OPENROUTER_API_KEY:
        providers.append(
            OpenAICompatibleJudgeProvider(
                "openrouter",
                config.OPENROUTER_JUDGE_MODEL,
                config.OPENROUTER_API_KEY,
                config.OPENROUTER_BASE_URL,
                {"HTTP-Referer": config.OPENROUTER_SITE_URL, "X-Title": "HR Hub AI"},
            )
        )
    return providers


def query_judge(requirements: list[str], evidence: list[str]) -> JudgeResponse:
    assert_clean("\n".join(evidence))
    providers = configured_judge_chain()
    if not providers:
        raise JudgeProviderError("No judge provider is configured")
    last_error: Exception | None = None
    for provider in providers:
        try:
            result = provider.evaluate(requirements, evidence)
            logger.info("Judge answered via provider=%s model=%s", result.provider, result.model)
            return result
        except JudgeProviderError as error:
            logger.warning("Judge provider failed provider=%s model=%s error=%s", provider.name, provider.model, error)
            last_error = error
    raise JudgeProviderError(f"All judge providers failed: {last_error}") from last_error
```

---

### 1.3 `ai-service/app/schemas/cv.py`
```python
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


class SkillEvaluation(StrictModel):
    requirement: str
    satisfaction_percent: float = Field(ge=0.0, le=100.0)
    reasoning: str
    evidence_quote: str


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
```

---

### 1.4 `ai-service/app/pipeline/run.py`
```python
"""
app/pipeline/run.py

بيربط خطوات الـ pipeline كلها ورا بعض: extract -> normalize -> prompt -> model -> validate.
ده المكان اللي فيه orchestration بس - مفيش أي HTTP/Flask logic هنا خالص.

المنطق ده كان قبل كده متوزع مباشرة جوه route handler في app.py القديم.
اتنقل هنا حرفيًا زي ما هو (نفس الخطوات، نفس الترتيب، نفس الـ exceptions) عشان:
- app/main.py يفضل مسؤول بس عن HTTP concerns (request/response/status codes)
- منطق الـ pipeline نفسه يبقى قابل لإعادة الاستخدام (من CLI أو test أو worker)
  من غير ما يكون مربوط بـ Flask

ملحوظة تنضيف: كان فيه هنا نسخة تانية (run_cv_extraction) بتعتمد على
ProviderAdapter/PromptRegistry بتوع مسار الـ FastAPI اللي اتشال لأنه مكنش
متوصّل (مفيش حاجة كانت بتعمل build_provider() فعليًا وقت الـ runtime).
اتشالت من هنا عشان الملف يفضل قابل للاستيراد من غير ImportError. المسار
الوحيد الشغال دلوقتي هو clean_and_query() -> app/main.py (Flask).
"""

import hashlib
import inspect
import json

from app.pipeline.extract_text_docx import extract_text_from_docx
from app.pipeline.extract_text_pdf import extract_text_from_pdf
from app.cache.cache_backend import cache_backend
from app.pipeline.normalize import clean_cv_text
from app.pipeline.postprocess import (
    extract_json_from_model_output,
    normalize_model_output,
)
from app.pipeline.redact import assert_clean, extract_contact_info, redact
from app.prompts.registry import build_prompt
from app.providers.hf_provider import query_model
from app.schemas.cv import CVSchema, JobDescription, RankingResult
from app.skills.canonicalize import canonicalise, extract_explicit_skills
from config.settings import config

EXTRACTION_PROMPT_VERSION = "cv-extraction-v1"
SCHEMA_VERSION = "cv-schema-v1"
TAXONOMY_VERSION = "2026.09"
SNAPSHOT_TTL_SECONDS = 3600.0
SNAPSHOT_MAX_ENTRIES = 128
_last_extraction_metadata: dict[str, object] = {}


def get_extraction_metadata() -> dict[str, object]:
    return dict(_last_extraction_metadata)


def _snapshot_key(
    source_text: str,
) -> str:
    configuration = {
        "document_hash": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        "prompt_version": EXTRACTION_PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "models": config.MODEL_CHAIN,
    }
    return hashlib.sha256(
        json.dumps(configuration, sort_keys=True).encode("utf-8")
    ).hexdigest()


def ranking_cache_key(candidate: CVSchema, job_description: JobDescription) -> str:
    candidate_json = json.dumps(
        candidate.model_dump(), sort_keys=True, ensure_ascii=False
    )
    configuration = {
        "candidate_hash": hashlib.sha256(candidate_json.encode("utf-8")).hexdigest(),
        "job_description_hash": hashlib.sha256(
            json.dumps(
                job_description.model_dump(), sort_keys=True, ensure_ascii=False
            ).encode("utf-8")
        ).hexdigest(),
        "judge_prompt_version": "ranking-judge-v1",
        "taxonomy_version": TAXONOMY_VERSION,
        "judge_model_chain": config.JUDGE_MODEL_CHAIN,
    }
    return hashlib.sha256(
        json.dumps(configuration, sort_keys=True).encode("utf-8")
    ).hexdigest()


def get_cached_ranking(
    candidate: CVSchema, job_description: JobDescription
) -> RankingResult | None:
    cache_key = f"judge:{ranking_cache_key(candidate, job_description)}"
    cached = cache_backend.get(cache_key)
    if not cached or "ranking" not in cached:
        return None
    try:
        return RankingResult(**cached["ranking"])
    except Exception:
        return None


def store_cached_ranking(
    candidate: CVSchema, job_description: JobDescription, result: RankingResult
) -> None:
    cache_backend.set(
        f"judge:{ranking_cache_key(candidate, job_description)}",
        {"ranking": result.model_dump()},
        config.CACHE_TTL_SECONDS,
    )


def extraction_status(cv: CVSchema) -> str:
    """Classify successful extraction without confusing it with model failure."""
    has_evidence = any(
        (
            cv.skills,
            cv.inferred_skills,
            cv.experience,
            cv.projects,
            cv.education,
            cv.certifications,
            cv.languages,
            cv.personal_info.name,
        )
    )
    return "SUCCESS" if has_evidence else "EMPTY"


def extract_raw_text(filepath: str, ext: str) -> str:
    """بتستدعي الـ extractor المناسب حسب امتداد الملف."""
    if ext == ".pdf":
        return extract_text_from_pdf(filepath)
    if ext == ".docx":
        return extract_text_from_docx(filepath)
    raise ValueError(f"Unsupported extension: {ext}")


def parse_and_validate(raw_output: str) -> CVSchema:
    """
    بتتحول من نص خام لموديل واحد إلى CVSchema متحقق منها بالكامل.

    Raises:
        JSONExtractionError: لو تعذر استخراج/تحليل JSON من النص.
        pydantic.ValidationError: لو الـ JSON متحلل لكن مش مطابق للـ schema.
    """
    raw_cv_data = extract_json_from_model_output(raw_output)
    raw_cv_data = normalize_model_output(raw_cv_data)
    return CVSchema(**raw_cv_data)


def clean_and_query(raw_text: str) -> CVSchema:
    """
    بتاخد النص الخام، تنضفه، تشيل منه الـ PII (redact) قبل ما يتبنى منه أي prompt،
    تبني الـ prompt عن طريق build_prompt() الثابتة، وتستدعي hf_provider.query_model()
    مباشرة مع الـ validation + fallback chain بتاعته.

    ملحوظة تصميم مهمة: email و phone بيتشالوا من النص المرسل للموديل (زي أي PII
    تاني)، لكن schema الناتج لازم يفضل فيه القيمتين دول. الحل: بنستخرجهم بـ regex
    من النص الأصلي *قبل* الـ redact (deterministic، مفيش داعي لموديل خارجي أصلاً)،
    ونحطهم في الـ CVSchema الراجع بعد ما الموديل يرد - بدل ما نسيب الموديل يحاول
    يقرا إيميل/تليفون هو أصلاً متبعتلوش.

    Raises:
        ModelInferenceError: فشل الاستدلال عبر كل الموديلات في MODEL_CHAIN.
    """
    cleaned_text = clean_cv_text(raw_text)
    cache_key = _snapshot_key(cleaned_text)

    # لازم نستخرج الـ contact info قبل الـ redact - بعد الـ redact مفيش إيميل/تليفون
    # حقيقي يتقرا خالص، هيبقوا استبدلوا بـ [EMAIL]/[PHONE].
    contact_info = extract_contact_info(cleaned_text)

    cached = cache_backend.get(f"snapshot:{cache_key}")
    if cached is not None:
        try:
            cv = CVSchema(**cached["cv"])
            _last_extraction_metadata.clear()
            _last_extraction_metadata.update(
                {
                    "cache_hit": True,
                    "model_used": "versioned-in-memory-snapshot",
                    "provider": None,
                    "attempt_number": 0,
                    "fallback_occurred": False,
                    "taxonomy_recovered_skills": cached.get(
                        "taxonomy_recovered_skills", []
                    ),
                }
            )
            if contact_info["email"]:
                cv.personal_info.email = contact_info["email"]
            if contact_info["phone"]:
                cv.personal_info.phone = contact_info["phone"]
            return cv
        except Exception:
            cached = None

    # نشيل PII (إيميل، تليفون، رقم قومي، أي رقم طويل) قبل ما النص يسيب المنصة
    # لأي third-party model provider (HF Inference Providers).
    redacted_text, _removed_count = redact(cleaned_text)

    system_prompt, user_prompt = build_prompt(redacted_text)

    # Safety net: لو أي identifier اتسرب رغم الـ redact() (bug في الـ regex نفسه
    # أو حالة حافة مش متغطية)، نرفض نبعت الـ payload خالص بدل ما نكمل. ده نفس
    # القاعدة الموصوفة في docstring app/pipeline/redact.py.
    assert_clean(system_prompt + user_prompt)

    model_metadata: dict[str, object] = {}
    if "metadata" in inspect.signature(query_model).parameters:
        cv = query_model(
            system_prompt,
            user_prompt,
            validate_fn=parse_and_validate,
            metadata=model_metadata,
        )
    else:
        # Preserve compatibility with tests/adapters implementing the old API.
        cv = query_model(system_prompt, user_prompt, validate_fn=parse_and_validate)

    # Preserve explicit taxonomy skills even when the model places them in an
    # inferred category instead of the literal skills field.
    explicit_skills = extract_explicit_skills(redacted_text)
    model_skill_ids = {
        canonicalise(skill)
        for skill in cv.skills + cv.inferred_skills
        if canonicalise(skill) is not None
    }
    taxonomy_recovered_skills = [
        skill
        for skill in explicit_skills
        if canonicalise(skill) not in model_skill_ids
    ]
    cv.skills = list(dict.fromkeys(cv.skills + explicit_skills))
    cache_backend.set(
        f"snapshot:{cache_key}",
        {
            "cv": cv.model_dump(),
            "taxonomy_recovered_skills": taxonomy_recovered_skills,
        },
        config.CACHE_TTL_SECONDS,
    )
    _last_extraction_metadata.clear()
    _last_extraction_metadata.update(
        {
            "cache_hit": False,
            "taxonomy_recovered_skills": taxonomy_recovered_skills,
            **model_metadata,
        }
    )

    # نفضّل القيمة اللي استخرجناها إحنا بالـ regex (أدق ومضمونة) فوق أي حاجة
    # رجّعها الموديل - أصلاً الموديل مبقاش شايف الإيميل/التليفون الحقيقيين.
    if contact_info["email"]:
        cv.personal_info.email = contact_info["email"]
    if contact_info["phone"]:
        cv.personal_info.phone = contact_info["phone"]

    return cv
```

---

### 1.5 `ai-service/app/cache/cache_backend.py`
```python
"""Resilient Redis-first cache with an in-memory fallback."""
from __future__ import annotations

import json
import logging
import time
from collections import OrderedDict
from typing import Any

import redis

from config.settings import config

logger = logging.getLogger(__name__)


class CacheBackend:
    def get(self, key: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def set(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        raise NotImplementedError


class InMemoryCacheBackend(CacheBackend):
    def __init__(self, max_entries: int = 128) -> None:
        self._entries: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self._max_entries = max_entries

    def get(self, key: str) -> dict[str, Any] | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        created_at, value = entry
        if time.monotonic() - created_at >= config.CACHE_TTL_SECONDS:
            self._entries.pop(key, None)
            return None
        self._entries.move_to_end(key)
        return value

    def set(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        self._entries[key] = (time.monotonic(), value)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)


class RedisCacheBackend(CacheBackend):
    def __init__(self, url: str, fallback: InMemoryCacheBackend) -> None:
        self._redis = redis.Redis.from_url(url, decode_responses=True)
        self._fallback = fallback
        self._healthy = False
        try:
            self._redis.ping()
            self._healthy = True
            logger.info("Redis cache connected")
        except redis.RedisError as error:
            logger.warning("Redis cache unavailable; using in-memory fallback: %s", error)

    def get(self, key: str) -> dict[str, Any] | None:
        if not self._healthy:
            return self._fallback.get(key)
        try:
            raw = self._redis.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except (redis.RedisError, json.JSONDecodeError, TypeError) as error:
            logger.warning("Redis cache read failed; using in-memory fallback: %s", error)
            self._healthy = False
            return self._fallback.get(key)

    def set(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        if not self._healthy:
            self._fallback.set(key, value, ttl_seconds)
            return
        try:
            self._redis.setex(key, ttl_seconds, json.dumps(value, ensure_ascii=False))
        except (redis.RedisError, TypeError, ValueError) as error:
            logger.warning("Redis cache write failed; using in-memory fallback: %s", error)
            self._healthy = False
            self._fallback.set(key, value, ttl_seconds)


def build_cache_backend() -> CacheBackend:
    fallback = InMemoryCacheBackend(max_entries=config.CACHE_MAX_ENTRIES)
    if not config.REDIS_URL:
        logger.warning("REDIS_URL is not configured; using in-memory cache fallback")
        return fallback
    return RedisCacheBackend(config.REDIS_URL, fallback)


cache_backend = build_cache_backend()
```

---

### 1.6 `ai-service/config/settings.py`
```python
"""
config/settings.py

مسؤول عن قراءة كل إعدادات المشروع من ملف .env بشكل مركزي.
باقي الملفات هتستورد من هنا بدل ما تقرأ os.environ بنفسها في أماكن متفرقة.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    
    # ============================================================
    # Service-to-service auth (app/security/auth.py)
    # ============================================================
    # ثابت بين الـ ai-service وأي حد بيناديه (غالبًا الـ full-stack backend).
    # لو سايبه فاضي، الـ endpoints بتفضل شغالة من غير حماية - مقبول للتطوير
    # المحلي بس، خطر لو السيرفر متاح لغير جهازك.
    AI_SERVICE_API_KEY: str = os.getenv("AI_SERVICE_API_KEY", "")

    # Semantic judge providers. Empty keys disable that provider in the chain.
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    GEMINI_JUDGE_MODEL: str = os.getenv("GEMINI_JUDGE_MODEL", "gemini-3.8-flash")
    GROQ_JUDGE_MODEL: str = os.getenv("GROQ_JUDGE_MODEL", "openai/gpt-oss-120b")
    OPENROUTER_JUDGE_MODEL: str = os.getenv(
        "OPENROUTER_JUDGE_MODEL", "meta-llama/llama-3.3-70b-instruct:free"
    )
    GROQ_BASE_URL: str = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    OPENROUTER_BASE_URL: str = os.getenv(
        "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
    )
    OPENROUTER_SITE_URL: str = os.getenv("OPENROUTER_SITE_URL", "http://localhost")
    JUDGE_TIMEOUT_SECONDS: int = int(os.getenv("JUDGE_TIMEOUT_SECONDS", "60"))

    REDIS_URL: str = os.getenv("REDIS_URL", "redis://redis:6379/0")
    CACHE_TTL_SECONDS: int = int(os.getenv("CACHE_TTL_SECONDS", "3600"))
    CACHE_MAX_ENTRIES: int = int(os.getenv("CACHE_MAX_ENTRIES", "128"))
    
    # ============================================================
    # Hugging Face
    # ============================================================
    HF_API_TOKEN: str = os.getenv("HF_API_TOKEN", "")

    # سلسلة الموديلات بالترتيب - لو الأول فشل بسبب quota/rate-limit
    # (402 Payment Required / 429 Too Many Requests)، بنجرب اللي بعده.
    #
    # مهم: كل (repo_id, provider) لازم يكونوا متأكدين إنهم متاحين مع بعض
    # فعليًا على HF Inference Providers. تأكد من صفحة الموديل على
    # huggingface.co (تبويب "Inference Providers") قبل ما تضيف عنصر هنا -
    # الدعم ده بيتغير مع الوقت (مثال: Mistral-7B-Instruct-v0.3 مش مدعوم
    # بأي provider حاليًا، لكن v0.2 مدعوم عن طريق Featherless AI).
    MODEL_CHAIN: list[dict[str, str]] = [
        {
            "repo_id": os.getenv("HF_MODEL_ID_1", "Qwen/Qwen2.5-3B-Instruct"),
            "provider": os.getenv("HF_PROVIDER_1", "featherless-ai"),
        },
        {
            "repo_id": os.getenv("HF_MODEL_ID_2", "mistralai/Mistral-7B-Instruct-v0.2"),
            "provider": os.getenv("HF_PROVIDER_2", "featherless-ai"),
        },
    ]

    # ============================================================
    # Flask
    # ============================================================
    FLASK_DEBUG: bool = os.getenv("FLASK_DEBUG", "False").lower() == "true"
    FLASK_PORT: int = int(os.getenv("FLASK_PORT", "5000"))

    # ============================================================
    # Upload settings
    # ============================================================
    UPLOAD_FOLDER: str = os.getenv("UPLOAD_FOLDER", "data")
    ALLOWED_EXTENSIONS = {".pdf", ".docx"}
    MAX_CONTENT_LENGTH: int = 10 * 1024 * 1024  # 10MB

    # ============================================================
    # Model generation settings
    # ============================================================
    MAX_NEW_TOKENS: int = int(os.getenv("MAX_NEW_TOKENS", "4096"))
    MODEL_TIMEOUT_SECONDS: int = int(os.getenv("MODEL_TIMEOUT_SECONDS", "60"))

    # ============================================================
    # Feature flags (kill switch لكل feature - قاعدة رقم 6 في README.md)
    # ============================================================
    RANKING_ENABLED: bool = os.getenv("RANKING_ENABLED", "True").lower() == "true"

    @property
    def JUDGE_MODEL_CHAIN(self) -> list[dict[str, str]]:
        return [
            {"provider": "gemini", "model": self.GEMINI_JUDGE_MODEL},
            {"provider": "groq", "model": self.GROQ_JUDGE_MODEL},
            {"provider": "openrouter", "model": self.OPENROUTER_JUDGE_MODEL},
        ]

    @classmethod
    def validate(cls) -> None:
        """بتتأكد إن الإعدادات الأساسية موجودة قبل ما نشغّل السيرفر."""
        if not cls.HF_API_TOKEN:
            raise RuntimeError(
                "HF_API_TOKEN مش موجود. تأكد إنك حاطط التوكن بتاعك في ملف .env "
                "بالشكل ده: HF_API_TOKEN=hf_xxxxxxxxxxxx"
            )
        if not cls.MODEL_CHAIN:
            raise RuntimeError(
                "MODEL_CHAIN فاضية - لازم يكون فيه موديل واحد على الأقل."
            )


config = Config()


# ============================================================
# Embedding settings (app/providers/embeddings.py بيستخدمها في
# semantic_fit() - جزء من الـ ranking pipeline الشغال فعليًا).
#
# ملحوظة تنضيف: الكلاس ده كان في الأصل جزء من "Settings" أكبر بكتير
# (Sprint 2 - FastAPI + provider abstraction) اللي اتشالت لأنها مكنتش
# متوصّلة/شغالة. سيبنا بس الحقلين اللي embeddings.py فعليًا محتاجهم.
# ============================================================

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # "local" = sentence-transformers على جهازك (زي ما كان).
    # "api"   = أي مزود متوافق مع OpenAI embeddings API (Gemini، OpenAI، إلخ).
    embedding_provider: str = Field(default="local", alias="EMBEDDING_PROVIDER")

    embedding_model: str = Field(default="BAAI/bge-m3", alias="EMBEDDING_MODEL")
    embedding_device: str = Field(default="cpu", alias="EMBEDDING_DEVICE")

    # إعدادات مزود الـ API (لما embedding_provider="api")
    embedding_api_base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta/openai/",
        alias="EMBEDDING_API_BASE_URL",
    )
    embedding_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    embedding_api_model: str = Field(default="gemini-embedding-001", alias="EMBEDDING_API_MODEL")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

---

### 1.7 Skill Matching & Canonicalization Module

#### `ai-service/app/skills/canonicalize.py`
```python
"""Map a free-text skill name to a canonical id.

Exact and alias matching first; fuzzy only above a high threshold, because a wrong
canonicalisation silently merges two different skills.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re

import yaml
from rapidfuzz import fuzz, process

TAXONOMY = Path(__file__).parent / "taxonomy.yaml"
FUZZY_THRESHOLD = 92


def _normalise_key(value: str) -> str:
    """Normalize presentation differences without inventing aliases."""
    return "".join(character for character in value.casefold() if character.isalnum())


@lru_cache
def _lookup() -> dict[str, str]:
    data = yaml.safe_load(TAXONOMY.read_text(encoding="utf-8"))
    table: dict[str, str] = {}
    for s in data["skills"]:
        table[_normalise_key(s["name"])] = s["id"]
        for alias in s.get("aliases", []):
            table[_normalise_key(alias)] = s["id"]
    return table


def canonicalise(name: str) -> str | None:
    table = _lookup()
    key = _normalise_key(name.strip())
    if key in table:
        return table[key]

    match = process.extractOne(key, table.keys(), scorer=fuzz.WRatio)
    if match and match[1] >= FUZZY_THRESHOLD:
        return table[match[0]]

    # Unknown skill. Return None rather than inventing an id — unknown skills are a
    # signal that the taxonomy needs extending, and that signal should be visible.
    return None


@lru_cache
def _taxonomy_terms() -> tuple[tuple[str, str], ...]:
    data = yaml.safe_load(TAXONOMY.read_text(encoding="utf-8"))
    terms: list[tuple[str, str]] = []
    for skill in data["skills"]:
        display = skill["name"]
        terms.append((display, display))
        terms.extend((display, alias) for alias in skill.get("aliases", []))
    return tuple(terms)


def extract_explicit_skills(text: str) -> list[str]:
    """Recover taxonomy skills that are explicitly named in source text."""
    found: list[str] = []
    seen: set[str] = set()
    for display, term in sorted(_taxonomy_terms(), key=lambda item: len(item[1]), reverse=True):
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, flags=re.IGNORECASE):
            canonical = canonicalise(display)
            if canonical and canonical not in seen:
                seen.add(canonical)
                found.append(display)
    return found
```

#### `ai-service/app/skills/taxonomy.yaml`
```yaml
# ────────────────────────────────────────────────────────────
# Skill taxonomy. Every skill the system recognises, with its
# aliases. Without this, "Scikit-learn", "scikit learn" and
# "sklearn" are three different skills and ranking breaks.
#
# Grow this from the requirement checklists of the ten job
# profiles — those are the skills that actually matter.
#
# ملحوظة (Sprint 2 - CV/JD Ranking): الإضافات اللي تحت خط
# "--- Sprint 2 additions ---" اتحطت بناءً على تخمين من نفس
# الفئات الأربعة الموجودة أصلًا (Data/BI, Frontend/Mobile, QA,
# Security) - مفيش checklists فعلية لعشر الوظائف موجودة في
# المشروع وقت كتابة السطور دي. لازم تتراجع/تتعدّل لما الـ
# checklists الحقيقية تتوفر.
# ────────────────────────────────────────────────────────────

skills:
  - id: skill.python
    name: Python
    aliases: [python3, "python 3", py]
    category: language

  - id: skill.sql
    name: SQL
    aliases: [t-sql, tsql, "structured query language"]
    category: language

  - id: skill.pandas
    name: Pandas
    aliases: [pandas]
    category: library

  - id: skill.sklearn
    name: Scikit-learn
    aliases: [sklearn, "scikit learn", scikitlearn]
    category: library

  - id: skill.xgboost
    name: XGBoost
    aliases: [xgb, "x-gboost"]
    category: library

  - id: skill.powerbi
    name: Power BI
    aliases: [powerbi, "power-bi", pbi]
    category: tool

  - id: skill.dax
    name: DAX
    aliases: ["data analysis expressions"]
    category: language

  - id: skill.excel
    name: Excel
    aliases: ["microsoft excel", "ms excel"]
    category: tool

  - id: skill.tableau
    name: Tableau
    aliases: []
    category: tool

  - id: skill.azure_ml
    name: Azure ML
    aliases: ["azure machine learning", azureml]
    category: platform

  - id: skill.react
    name: React
    aliases: [reactjs, "react.js"]
    category: framework

  - id: skill.flutter
    name: Flutter
    aliases: []
    category: framework

  - id: skill.selenium
    name: Selenium
    aliases: [webdriver]
    category: tool

  - id: skill.siem
    name: SIEM
    aliases: [splunk, qradar, "security information and event management"]
    category: domain

  # ──────────────────────────────────────────────────────────
  # --- Sprint 2 additions (تخمين - راجع الملحوظة فوق) ---
  # ──────────────────────────────────────────────────────────

  # --- Data / BI ---
  - id: skill.numpy
    name: NumPy
    aliases: [numpy]
    category: library

  - id: skill.matplotlib
    name: Matplotlib
    aliases: [matplotlib, "matplotlib.pyplot"]
    category: library

  - id: skill.mysql
    name: MySQL
    aliases: ["my sql"]
    category: tool

  - id: skill.postgresql
    name: PostgreSQL
    aliases: [postgres, "postgre sql"]
    category: tool

  - id: skill.tensorflow
    name: TensorFlow
    aliases: [tf]
    category: library

  - id: skill.pytorch
    name: PyTorch
    aliases: [torch]
    category: library

  # --- Frontend / Mobile / Web ---
  - id: skill.javascript
    name: JavaScript
    aliases: [js, "java script"]
    category: language

  - id: skill.typescript
    name: TypeScript
    aliases: [ts]
    category: language

  - id: skill.html_css
    name: HTML/CSS
    aliases: [html, css, "html5", "css3"]
    category: language

  - id: skill.nodejs
    name: Node.js
    aliases: [node, nodejs, "node js"]
    category: platform

  - id: skill.vuejs
    name: Vue.js
    aliases: [vue, vuejs]
    category: framework

  - id: skill.angular
    name: Angular
    aliases: [angularjs]
    category: framework

  - id: skill.kotlin
    name: Kotlin
    aliases: []
    category: language

  - id: skill.swift
    name: Swift
    aliases: []
    category: language

  # --- QA ---
  - id: skill.appium
    name: Appium
    aliases: []
    category: tool

  - id: skill.postman
    name: Postman
    aliases: []
    category: tool

  - id: skill.jira
    name: Jira
    aliases: []
    category: tool

  # --- Security ---
  - id: skill.penetration_testing
    name: Penetration Testing
    aliases: [pentest, "pen testing", "pen-testing"]
    category: domain

  - id: skill.nmap
    name: Nmap
    aliases: []
    category: tool

  - id: skill.wireshark
    name: Wireshark
    aliases: []
    category: tool

  # --- Cross-cutting engineering tools ---
  - id: skill.git
    name: Git
    aliases: [github, gitlab]
    category: tool

  - id: skill.docker
    name: Docker
    aliases: [containerization]
    category: tool

  - id: skill.aws
    name: AWS
    aliases: ["amazon web services"]
    category: platform

  - id: skill.azure
    name: Azure
    aliases: ["microsoft azure"]
    category: platform

  - id: skill.gcp
    name: GCP
    aliases: ["google cloud", "google cloud platform"]
    category: platform

  # --- AI instruction and creative AI ---
  - id: skill.chatgpt
    name: ChatGPT
    aliases: [chatgpt, "chat gpt"]
    category: ai_assistant

  - id: skill.claude
    name: Claude
    aliases: []
    category: ai_assistant

  - id: skill.gemini
    name: Gemini
    aliases: ["google gemini"]
    category: ai_assistant

  - id: skill.microsoft_copilot
    name: Microsoft Copilot
    aliases: [copilot]
    category: ai_assistant

  - id: skill.perplexity
    name: Perplexity
    aliases: []
    category: ai_assistant

  - id: skill.google_ai_studio
    name: Google AI Studio
    aliases: ["ai studio"]
    category: ai_assistant

  - id: skill.notebooklm
    name: NotebookLM
    aliases: ["notebook lm"]
    category: ai_assistant

  - id: skill.prompt_engineering
    name: Prompt Engineering
    aliases: []
    category: ai_practice

  - id: skill.ai_image_generation
    name: AI Image Generation
    aliases: []
    category: generative_ai

  - id: skill.midjourney
    name: Midjourney
    aliases: []
    category: generative_ai

  - id: skill.chatgpt_image_generation
    name: ChatGPT Image Generation
    aliases: ["chatgpt image gen"]
    category: generative_ai

  - id: skill.adobe_firefly
    name: Adobe Firefly
    aliases: [firefly]
    category: generative_ai

  - id: skill.leonardo_ai
    name: Leonardo AI
    aliases: [leonardo]
    category: generative_ai

  - id: skill.flux
    name: Flux
    aliases: []
    category: generative_ai

  - id: skill.ideogram
    name: Ideogram
    aliases: []
    category: generative_ai

  - id: skill.recraft
    name: Recraft
    aliases: []
    category: generative_ai

  - id: skill.ai_video_generation
    name: AI Video Generation
    aliases: []
    category: generative_ai

  - id: skill.runway
    name: Runway
    aliases: ["runway ml"]
    category: generative_ai

  - id: skill.kling
    name: Kling
    aliases: []
    category: generative_ai

  - id: skill.pika
    name: Pika
    aliases: []
    category: generative_ai

  - id: skill.luma
    name: Luma
    aliases: []
    category: generative_ai

  - id: skill.heygen
    name: HeyGen
    aliases: ["hey gen"]
    category: generative_ai

  - id: skill.synthesia
    name: Synthesia
    aliases: []
    category: generative_ai

  - id: skill.elevenlabs
    name: ElevenLabs
    aliases: ["eleven labs"]
    category: generative_ai

  - id: skill.playht
    name: PlayHT
    aliases: ["play ht"]
    category: generative_ai

  - id: skill.adobe_podcast
    name: Adobe Podcast
    aliases: []
    category: generative_ai

  - id: skill.suno
    name: Suno
    aliases: []
    category: generative_ai

  - id: skill.udio
    name: Udio
    aliases: []
    category: generative_ai

  - id: skill.canva_ai
    name: Canva AI
    aliases: ["canva ai"]
    category: ai_design

  - id: skill.gamma
    name: Gamma
    aliases: []
    category: ai_design

  - id: skill.tome
    name: Tome
    aliases: []
    category: ai_design

  - id: skill.adobe_express
    name: Adobe Express
    aliases: []
    category: design

  - id: skill.figma_ai
    name: Figma AI
    aliases: []
    category: ai_design

  - id: skill.ai_copywriting
    name: AI Copywriting
    aliases: []
    category: ai_marketing

  - id: skill.social_media_content_creation
    name: Social Media Content Creation
    aliases: []
    category: ai_marketing

  - id: skill.email_marketing
    name: Email Marketing
    aliases: []
    category: marketing

  - id: skill.seo_with_ai
    name: SEO with AI
    aliases: ["ai seo"]
    category: ai_marketing

  - id: skill.content_strategy
    name: Content Strategy
    aliases: []
    category: marketing

  - id: skill.ai_marketing_campaigns
    name: AI Marketing Campaigns
    aliases: ["ai powered marketing campaigns"]
    category: ai_marketing

  - id: skill.branding_with_ai
    name: Branding with AI
    aliases: ["ai branding"]
    category: ai_marketing
```

---

### 1.8 Security Safeguards & Ingestion

#### `ai-service/app/security/auth.py`
```python
"""
app/security/auth.py

حماية بسيطة بـ API key ثابت بين الـ ai-service وأي حد بيناديه (غالبًا الـ
full-stack backend). دي خطوة أولى سريعة قبل الـ integration - مش بديل عن
auth layer حقيقي (JWT/OAuth) لو المشروع كبر واحتاج مستخدمين متعددين
بصلاحيات مختلفة. انظر docs/DECISIONS.md لتفاصيل القرار ده.
"""
from __future__ import annotations

import hmac
import logging
from functools import wraps

from flask import jsonify, request

from config.settings import config

logger = logging.getLogger(__name__)

_warned_once = False


def require_api_key(view_func):
    """
    بتتحقق من header اسمه X-API-Key ومطابق لـ config.AI_SERVICE_API_KEY.

    لو AI_SERVICE_API_KEY فاضي (مش متظبط في .env)، الـ endpoint بيفضل شغال
    من غير حماية - fail-open مقصود عشان التطوير المحلي والـ tests الحالية
    تفضل شغالة من غير تعديل، لكن بيطبع warning واحد بس في اللوج (مش في كل
    request) عشان ميتنساش قبل أي deployment حقيقي.
    """

    @wraps(view_func)
    def wrapped(*args, **kwargs):
        global _warned_once
        if not config.AI_SERVICE_API_KEY:
            if not _warned_once:
                logger.warning(
                    "AI_SERVICE_API_KEY مش متظبط - الـ endpoints شغالة من غير أي "
                    "حماية. مقبول للتطوير المحلي بس - لازم يتظبط قبل أي deployment "
                    "متاح لغير جهازك."
                )
                _warned_once = True
            return view_func(*args, **kwargs)

        provided = request.headers.get("X-API-Key", "")
        # hmac.compare_digest بدل == عشان نتجنب timing attack بسيط على طول المفتاح.
        if not hmac.compare_digest(provided, config.AI_SERVICE_API_KEY):
            return jsonify({"success": False, "error": "Missing or invalid API key."}), 401

        return view_func(*args, **kwargs)

    return wrapped
```

#### `ai-service/app/security/file_validator.py`
```python
"""
security/file_validator.py

كل منطق التحقق من أمان الملف المرفوع، معزول في مكان واحد:
1. التحقق من الامتداد
2. التحقق من المحتوى الحقيقي (magic bytes) مش بس اسم الملف
3. توليد اسم ملف آمن للتخزين المؤقت

ده كان قبل كده متوزع جوه app.py مباشرة. اتنقل هنا عشان:
- app.py يفضل بس orchestration (يستقبل request -> ينده الخطوات -> يرجع response)
- أي تعديل مستقبلي على قواعد الأمان (نوع ملفات جديد، فحص إضافي) يبقى
  في مكان واحد بدل ما يتوزع جوه route handler

(تحديث): بدل الاعتماد على مكتبة python-magic (اللي محتاجة libmagic كـ
native library غير متوفرة افتراضيًا على ويندوز)، بنتحقق يدويًا من أول
بايتات الملف (magic bytes / file signature) - نفس المبدأ بالظبط، بس
من غير أي تبعية خارجية على نظام التشغيل.
"""

import os
import uuid

from werkzeug.utils import secure_filename

# التوقيعات الثنائية (magic bytes) الحقيقية لبداية كل نوع ملف مسموح بيه.
# PDF: بيبدأ دايمًا بـ "%PDF-".
# DOCX: هو في الأساس أرشيف ZIP (Office Open XML)، فبيبدأ بتوقيع الـ ZIP القياسي.
_FILE_SIGNATURES: dict[str, list[bytes]] = {
    ".pdf": [b"%PDF-"],
    ".docx": [b"PK\x03\x04"],
}


class FileValidationError(Exception):
    """بترفع لو الملف مرفوض لأي سبب أمني (امتداد غير مسموح، محتوى مش مطابق، إلخ)."""
    pass


def validate_extension(filename: str, allowed_extensions: set[str]) -> str:
    """
    بتتحقق من امتداد الملف وترجعه (lowercase) لو مسموح بيه.

    Raises:
        FileValidationError: لو الامتداد مش مسموح.
    """
    ext = os.path.splitext(filename)[1].lower()
    if ext not in allowed_extensions:
        raise FileValidationError(
            f"Unsupported file extension: {ext}. Allowed: {sorted(allowed_extensions)}"
        )
    return ext


def validate_file_content(filepath: str, ext: str) -> None:
    """
    بتتأكد إن محتوى الملف الفعلي (أول بايتات منه) بيتطابق مع الامتداد المعلن،
    عن طريق مقارنتها بالتوقيع الثنائي (magic bytes) المعروف لكل نوع.
    ده بيمنع حد يسمي ملف مش pdf/docx فعليًا بامتداد .pdf أو .docx ويرفعه.

    Raises:
        FileValidationError: لو المحتوى مش مطابق للامتداد، أو تعذر
            قراءة الملف أصلاً.
    """
    signatures = _FILE_SIGNATURES.get(ext)
    if not signatures:
        raise FileValidationError(f"No known signature for extension: {ext}")

    try:
        with open(filepath, "rb") as f:
            header = f.read(8)
    except Exception as e:
        raise FileValidationError(f"Could not read file content: {e}") from e

    if not any(header.startswith(sig) for sig in signatures):
        raise FileValidationError(
            f"File content does not match declared extension ({ext})."
        )


def generate_safe_storage_name(original_filename: str) -> str:
    """
    بتولّد اسم ملف آمن للتخزين المؤقت: uuid عشوائي + نسخة منظفة من
    الاسم الأصلي (بس للقراءة/الـ logs، مش بيتم الاعتماد عليه في المسار).

    ده بيمنع path traversal (اسم ملف فيه ../../) وبيمنع تصادم/استبدال
    ملفات لو اتنين رفعوا ملف بنفس الاسم في نفس الوقت.
    """
    safe_name = secure_filename(original_filename)
    return f"{uuid.uuid4().hex}_{safe_name}"
```

#### Rate Limiting Configuration in `ai-service/app/main.py`
> **Note on Rate Limiting File:** Rate limiting is not defined in a standalone `limiter.py` file. It is instantiated and attached directly in `ai-service/app/main.py` using `flask_limiter.Limiter(get_remote_address, app=app, default_limits=["30 per hour"])` and endpoint decorator `@limiter.limit("10 per hour")`.

Below is the complete source of `ai-service/app/main.py`:
```python
"""
app/main.py

نقطة الدخول الرئيسية للـ Flask API.
بيربط الـ pipeline اللي شغال بالفعل (extraction -> prompt -> model -> json)
خلف endpoints بسيطة.
"""

import json
import logging
import os

from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from pydantic import ValidationError as PydanticValidationError

from config.settings import config
from app.pipeline.ranking import rank as compute_ranking
from app.pipeline.run import (
    clean_and_query,
    extract_raw_text,
    extraction_status,
    get_extraction_metadata,
)
from app.providers.hf_provider import ModelInferenceError
from app.providers.judge_provider import JudgeProviderError
from app.schemas.cv import CVSchema, JobDescription
from app.security.auth import require_api_key
from app.security.file_validator import (
    FileValidationError,
    generate_safe_storage_name,
    validate_extension,
    validate_file_content,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH

os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)

# rate limiting عام على مستوى الـ app + حد أخص على endpoint الاستخراج
limiter = Limiter(get_remote_address, app=app, default_limits=["30 per hour"])


@app.route("/api/v1/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/api/v1/cv/evaluate", methods=["POST"])
@require_api_key
@limiter.limit("10 per hour")
def evaluate_cv():
    if "file" not in request.files:
        return jsonify({"success": False, "error": "No 'file' field in form-data."}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"success": False, "error": "No file selected."}), 400

    job_description_raw = request.form.get("job_description")
    if job_description_raw is None:
        return jsonify({"success": False, "error": "Missing 'job_description' field in form-data."}), 400

    try:
        job_description_payload = json.loads(job_description_raw)
    except json.JSONDecodeError:
        return jsonify({"success": False, "error": "job_description must be valid JSON."}), 400

    if not isinstance(job_description_payload, dict):
        return jsonify({"success": False, "error": "job_description must be a JSON object."}), 400

    try:
        job_description = JobDescription(**job_description_payload)
    except PydanticValidationError as e:
        return jsonify({"success": False, "error": e.errors()}), 422

    try:
        ext = validate_extension(file.filename, config.ALLOWED_EXTENSIONS)
    except FileValidationError as e:
        return jsonify({"success": False, "error": str(e)}), 400

    temp_name = generate_safe_storage_name(file.filename)
    temp_path = os.path.join(config.UPLOAD_FOLDER, temp_name)

    try:
        file.save(temp_path)

        try:
            validate_file_content(temp_path, ext)
        except FileValidationError as e:
            return jsonify({"success": False, "error": str(e)}), 400

        raw_text = extract_raw_text(temp_path, ext)
        if not raw_text or not raw_text.strip():
            return jsonify({"success": False, "error": "No extractable text found in file."}), 422

        try:
            validated_cv = clean_and_query(raw_text)
        except ModelInferenceError as e:
            logger.error("Model inference/validation failed across full chain: %s", e)
            return jsonify(
                {
                    "success": False,
                    "error": "Model inference failed. Please try again.",
                    "extraction_status": "FAILED",
                }
            ), 502

        status = extraction_status(validated_cv)

        if status == "EMPTY":
            return jsonify(
                {
                    "success": True,
                    "cv": validated_cv.model_dump(),
                    "ranking": None,
                    "extraction_status": "EMPTY",
                    "extraction_metadata": get_extraction_metadata(),
                }
            ), 200

        if not config.RANKING_ENABLED:
            return jsonify(
                {
                    "success": True,
                    "cv": validated_cv.model_dump(),
                    "ranking": None,
                    "extraction_status": status,
                    "extraction_metadata": get_extraction_metadata(),
                }
            ), 200

        try:
            ranking_result = compute_ranking(validated_cv, job_description)
        except (ModelInferenceError, JudgeProviderError):
            logger.error("Ranking judge failed across full model chain")
            return jsonify(
                {
                    "success": False,
                    "error": "Ranking model inference failed. Please try again.",
                }
            ), 502
        except Exception:
            logger.exception("Unexpected error during ranking")
            return jsonify({"success": False, "error": "Internal server error."}), 500

        return jsonify(
            {
                "success": True,
                "cv": validated_cv.model_dump(),
                "ranking": ranking_result.model_dump(),
                "extraction_status": status,
                "extraction_metadata": get_extraction_metadata(),
            }
        ), 200

    except Exception:
        logger.exception("Unexpected error during CV evaluation")
        return jsonify({"success": False, "error": "Internal server error."}), 500

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


if __name__ == "__main__":
    config.validate()
    app.run(debug=config.FLASK_DEBUG, port=config.FLASK_PORT)
```

---

## 2. Current Scoring Formula — Exact State

### 2.1 Verbatim Code Quotation from `app/pipeline/ranking.py`
The scoring calculation in `app/pipeline/ranking.py` lines 11–16 and 161–175 is:
```python
REQUIRED_WEIGHT = 0.8
NICE_TO_HAVE_WEIGHT = 0.2
TAXONOMY_VERSION = "2026.09"
JUDGE_PROMPT_VERSION = "ranking-judge-v1"
HARD_SKILL_WEIGHT = 1.0
SEMANTIC_WEIGHT = 0.0
...
    required_evaluations = evaluations[: len(required)]
    preferred_evaluations = evaluations[len(required) :]

    required_ratio = _average(required_evaluations)
    nice_ratio = _average(preferred_evaluations)
    if required_ratio is not None:
        preferred_bonus = NICE_TO_HAVE_WEIGHT * (nice_ratio or 0.0) * (1.0 - required_ratio)
        hard_skill_score = required_ratio + preferred_bonus
    else:
        preferred_bonus = 0.0
        hard_skill_score = NICE_TO_HAVE_WEIGHT * (nice_ratio or 0.0)

    final_score = HARD_SKILL_WEIGHT * hard_skill_score
    result = RankingResult(
        score=round(final_score * 100, 2),
```

### 2.2 Detailed Status of Scoring Formula Inquiries

1. **Is the scoring still the old single hard_skill_score formula, or has any part of a 70/20/10 redesign already been implemented?**
   - **Answer:** The scoring in active code is entirely the old single `hard_skill_score` formula. Zero parts of a 70/20/10 (Required / Nice-to-have / Experience) formula have been implemented in `app/pipeline/ranking.py` or anywhere else in the repository.

2. **Does a `source_multiplier` (1.0 explicit fields / 0.5 narrative-only) exist anywhere in the code?**
   - **Answer:** **No.** A codebase-wide search confirms `source_multiplier` does not exist in any Python module, YAML file, prompt, or schema.

3. **Does a `calculate_total_experience_years()` function (or equivalent) exist anywhere?**
   - **Answer:** **No.** There is no date parser, duration calculator, or experience summation function anywhere in the codebase.

4. **Are `SEMANTIC_WEIGHT` and `REQUIRED_WEIGHT` still present and still unused/dead?**
   - **Answer:** **Yes, both are present and dead:**
     - `REQUIRED_WEIGHT = 0.8` is defined at line 11 of `app/pipeline/ranking.py`. A search confirms it is never referenced anywhere else in the entire codebase.
     - `SEMANTIC_WEIGHT = 0.0` is defined at line 16 of `app/pipeline/ranking.py`. It is only passed as metadata into the `breakdown` dictionary at line 196; it has zero impact on `final_score`.

5. **Is `min_experience_years` used anywhere in scoring logic, or still just accepted by the schema and unused?**
   - **Answer:** `min_experience_years: Optional[int] = None` is accepted in `JobDescription` (`app/schemas/cv.py:59`), but it is **completely unused in `app/pipeline/ranking.py`** and has no effect on candidate scoring.

---

## 3. Test Suite State

### 3.1 Verbatim Pytest Output
The entire test suite was executed via `.venv\Scripts\pytest -v` from `ai-service/`:

```text
============================= test session starts =============================
platform win32 -- Python 3.14.3, pytest-9.1.1, pluggy-1.6.0
rootdir: D:\github project\HR_HUB_AI\ai-service
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.14.2, asyncio-1.4.0, cov-7.1.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 39 items

tests\integration\test_auth.py .....                                     [ 12%]
tests\integration\test_rank_endpoint.py ........                         [ 33%]
tests\unit\test_canonicalize.py .....                                    [ 46%]
tests\unit\test_embeddings.py .                                          [ 48%]
tests\unit\test_extraction_snapshot.py ....                              [ 58%]
tests\unit\test_extraction_status.py .                                   [ 61%]
tests\unit\test_hf_provider.py .                                         [ 64%]
tests\unit\test_ranking.py .........                                     [ 87%]
tests\unit\test_redaction.py ...                                         [ 94%]
tests\unit\test_redaction_integration.py ..                              [100%]

============================== warnings summary ===============================
.venv\Lib\site-packages\flask_limiter\_extension.py:364
  D:\github project\HR_HUB_AI\ai-service\.venv\Lib\site-packages\flask_limiter\_extension.py:364: UserWarning: Using the in-memory storage for tracking rate limits as no storage was explicitly specified. This is not recommended for production use. See: https://flask-limiter.readthedocs.io#configuring-a-storage-backend for documentation about configuring the storage backend.
    warnings.warn(

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=============================== tests coverage ================================
_______________ coverage: platform win32, python 3.14.3-final-0 _______________

Name                                Stmts   Miss  Cover   Missing
-----------------------------------------------------------------
app\__init__.py                         0      0   100%
app\cache\__init__.py                   0      0   100%
app\cache\cache_backend.py             73     26    64%   19, 22, 55-56, 61-71, 74-82, 88-89
app\main.py                            88     19    78%   63, 67, 75-76, 79, 99-100, 104, 144-154, 166-168, 176-177
app\pipeline\__init__.py                0      0   100%
app\pipeline\extract_text_docx.py      25     20    20%   35-65
app\pipeline\extract_text_pdf.py       28     22    21%   46-82
app\pipeline\normalize.py              15      2    87%   44, 66
app\pipeline\postprocess.py            70     61    13%   38-71, 90-98, 120-131, 135-159
app\pipeline\ranking.py               103     10    90%   25, 44, 81-90, 170-171
app\pipeline\redact.py                 20      0   100%
app\pipeline\run.py                    89     22    75%   67-81, 89-96, 102, 128-132, 143-145, 192-193
app\prompts\__init__.py                 0      0   100%
app\prompts\registry.py                20      7    65%   191-213
app\providers\__init__.py               0      0   100%
app\providers\embeddings.py            88     59    33%   21-24, 30, 45-48, 54, 64-68, 72-86, 105-124, 129-132, 136-143, 148-155
app\providers\hf_provider.py           63     26    59%   54-64, 71-96, 129, 158-167, 192
app\providers\judge_provider.py       141    102    28%   39, 42, 50-62, 74-78, 81-109, 121-123, 127-137, 140-206, 210-232, 236-249
app\schemas\__init__.py                 0      0   100%
app\schemas\cv.py                      68      3    96%   65, 69, 73
app\security\auth.py                   21      0   100%
app\security\file_validator.py         25      4    84%   66, 71-72, 75
app\skills\__init__.py                  0      0   100%
app\skills\canonicalize.py             47      1    98%   43
-----------------------------------------------------------------
TOTAL                                 984    384    61%
Required test coverage of 49.0% reached. Total coverage: 60.98%
======================== 39 passed, 1 warning in 4.93s ========================
```

### 3.2 Ranking & Scoring Test File Catalog

1. **`tests/unit/test_ranking.py` (9 tests):**
   - `test_taxonomy_filter_only_sends_relevant_requirements_to_judge`: Asserts requirements with candidate evidence are routed to the judge and satisfaction scores populated.
   - `test_fractional_required_and_preferred_scores_are_authoritative`: Asserts score arithmetic matches `required_ratio + 0.2 * nice_ratio * (1.0 - required_ratio)`.
   - `test_unknown_requirement_without_candidate_taxonomy_signal_is_zero`: Asserts requirement with empty evidence gets 0.0 satisfaction without invoking judge.
   - `test_certifications_are_forwarded_as_candidate_evidence`: Asserts `Certification: ...` items are passed into judge prompt.
   - `test_experience_descriptions_are_forwarded_as_candidate_evidence`: Asserts experience job titles and descriptions reach judge as evidence.
   - `test_indirect_database_evidence_reaches_judge_for_sql_requirement`: Asserts project descriptions are delivered to judge as candidate evidence.
   - `test_duplicate_requirements_are_deduplicated_before_judging`: Asserts requirements with identical canonical forms are deduplicated before judging.
   - `test_paraphrased_requirement_uses_candidate_domain_evidence`: Asserts paraphrased requirements receive evidence and evaluated fractional score.
   - `test_cached_ranking_is_returned_without_calling_judge`: Asserts pre-existing cached `RankingResult` bypasses judge query.

2. **`tests/integration/test_rank_endpoint.py` (8 tests):**
   - Asserts `/api/v1/cv/evaluate` end-to-end integration: multipart handling, payload validation, status codes (200, 400, 422, 502), kill switch (`RANKING_ENABLED=False`), `EMPTY` CV handling, and `extraction_metadata` response exposure.

3. **`tests/unit/test_canonicalize.py` (5 tests):**
   - Asserts alias normalization, unknown skill handling (`None`), AI domain term resolution, explicit extraction from narrative text, and strict word-boundary matching.

4. **`tests/unit/test_embeddings.py` (1 test):**
   - Asserts API embedding results preserve original input order after async/batched responses.

5. **`tests/unit/test_extraction_snapshot.py` (4 tests):**
   - Asserts snapshot caching by sha256 text hash, cache key invalidation upon `MODEL_CHAIN` changes, TTL expiration, and LRU eviction.

6. **`tests/unit/test_extraction_status.py` (1 test):**
   - Asserts distinction between `EMPTY` and `SUCCESS` extraction states.

7. **`tests/unit/test_hf_provider.py` (1 test):**
   - Asserts fallback progression across `MODEL_CHAIN` and fallback metadata recording.

8. **`tests/unit/test_redaction.py` (3 tests):**
   - Asserts PII identifiers (National ID, Email, Phone) are sanitized and verifies `assert_clean()` safety net.

9. **`tests/unit/test_redaction_integration.py` (2 tests):**
   - Asserts PII never enters prompts sent to LLMs, but locally extracted regex emails/phones are preserved in the final output.

10. **`tests/integration/test_auth.py` (5 tests):**
    - Asserts 401 on missing or incorrect `X-API-Key`, 200 on valid key, unauthenticated `/api/v1/health`, and fail-open behavior when `AI_SERVICE_API_KEY` is unset.

---

## 4. RankingResult / Breakdown Schema — Exact Current Shape

### 4.1 Verbatim Schemas from `app/schemas/cv.py`
```python
class SkillEvaluation(StrictModel):
    requirement: str
    satisfaction_percent: float = Field(ge=0.0, le=100.0)
    reasoning: str
    evidence_quote: str


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
```

### 4.2 Runtime `breakdown` Dictionary in `app/pipeline/ranking.py`
```python
        breakdown={
            "required_skills_total": len(required),
            "required_satisfaction_average": required_ratio,
            "nice_to_have_skills_total": len(preferred),
            "nice_to_have_satisfaction_average": nice_ratio,
            "preferred_bonus": round(preferred_bonus, 4),
            "hard_skill_score": round(hard_skill_score, 4),
            "hard_skill_weight": HARD_SKILL_WEIGHT,
            "semantic_weight": SEMANTIC_WEIGHT,
            "taxonomy_version": TAXONOMY_VERSION,
            "judge_prompt_version": JUDGE_PROMPT_VERSION,
            "scoring_version": "llm-capability-judge-v1",
        }
```

### 4.3 Field Presence Audit
| Field Name | Present in Current Code? | Location / Current Value |
|---|---|---|
| `source_multiplier` | **NO** | Absent from `SkillEvaluation` and `breakdown` |
| `final_skill_score` | **NO** | Absent (current field is `hard_skill_score`) |
| `required_component` | **NO** | Absent |
| `nice_to_have_component` | **NO** | Absent |
| `experience_component` | **NO** | Absent |
| `candidate_total_years` | **NO** | Absent |
| `experience_ratio` | **NO** | Absent |
| `scoring_version` | **YES** | Present in `breakdown`: `"llm-capability-judge-v1"` |

---

## 5. Architectural Deviations & Security Audit

1. **Security Layer Review (`auth.py`, `file_validator.py`, `limiter`):**
   - No unexpected changes.
   - `auth.py` strictly uses constant-time `hmac.compare_digest`. Fail-open when `AI_SERVICE_API_KEY` is unset is documented and tested for local dev ergonomics.
   - `file_validator.py` enforces extension checking and magic byte verification (`%PDF-`, `PK\x03\x04`).
   - Rate limiting uses `Limiter(get_remote_address, app=app, default_limits=["30 per hour"])` with in-memory storage fallback.

2. **Judge Evidence Redaction Chain (`redact()` -> `assert_clean()`):**
   - In `app/pipeline/ranking.py`:
     `_redacted_evidence(candidate)` applies `redact(item)` and immediately executes `assert_clean(redacted_item)` before accumulating evidence.
   - In `app/providers/judge_provider.py`:
     `query_judge(requirements, evidence)` enforces `assert_clean("\n".join(evidence))` before contacting any LLM provider.
   - No evidence bypass path exists.

3. **API Keys & Logging Audit:**
   - No hardcoded API keys exist in code.
   - All credentials (`HF_API_TOKEN`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `AI_SERVICE_API_KEY`) are sourced via `config/settings.py` from environment variables.
   - Log statements in `judge_provider.py` and `hf_provider.py` log provider names and model IDs only; no credential or token logging occurs.

4. **TODO / FIXME / Commented-Out Code Audit:**
   - No TODOs or commented-out code related to scoring or the 70/20/10 redesign exist in `app/`.
   - The only remaining TODOs in the workspace are in `eval/runners/run_ranking.py:109` (MLflow logging) and `eval/runners/run_extraction.py:36`.

---

## 6. Summary Status Table

| Item | Status | Note |
|---|---|---|
| **1. Source multiplier logic** | **Not started** | No 1.0 explicit / 0.5 narrative distinction or multiplier exists in `ranking.py`. |
| **2. Experience duration calculation** | **Not started** | No date parsing or experience year summing function exists; `min_experience_years` is accepted by schema but unused. |
| **3. 70/20/10 scoring formula** | **Not started** | Active code uses `hard_skill_score = required_ratio + 0.2 * nice_ratio * (1 - required_ratio)` with 0% experience weight. |
| **4. Output contract updates (breakdown fields)** | **Not started** | Breakdown dictionary and `SkillEvaluation` lack `source_multiplier`, `experience_component`, `experience_ratio`, etc. |
| **5. Full regression test pass** | **Fully implemented** | All 39 test cases in `tests/` pass with 100% success and 60.98% overall code coverage. |
| **6. Validation against real Mohamed Galal CV/JD pair** | **Partially implemented** | Representative junior QA verification is documented, but the actual real Mohamed Galal CV/JD files are absent from fixtures. |
