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
from app.prompts.registry import build_judge_prompt, build_semantic_judge_prompt
from app.schemas.cv import EnrichedRequirement, SkillEvaluation
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

    def evaluate_semantic(
        self, requirements: list[EnrichedRequirement], evidence: list[str]
    ) -> JudgeResponse:
        raise NotImplementedError

    def _messages(self, requirements: list[str], evidence: list[str]) -> tuple[str, str]:
        return build_judge_prompt(
            [{"requirement": requirement} for requirement in requirements], evidence
        )

    def _semantic_messages(
        self, requirements: list[EnrichedRequirement], evidence: list[str]
    ) -> tuple[str, str]:
        return build_semantic_judge_prompt(requirements, evidence)

    @staticmethod
    def _parse(
        raw_content: str, requirements: list[str], evidence: list[str]
    ) -> list[SkillEvaluation]:
        payload = extract_json_from_model_output(raw_content)
        items = payload.get("evaluations")
        if not isinstance(items, list) or len(items) != len(requirements):
            raise JudgeProviderError("Judge returned an unexpected evaluation count")
        
        # Build lookup maps for robust matching without failing on minor casing/whitespace variations
        raw_items_by_exact: dict[str, dict[str, Any]] = {}
        raw_items_by_casefold: dict[str, dict[str, Any]] = {}
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                raise JudgeProviderError("Judge evaluation item is not a dictionary")
            req_name = str(item.get("requirement") or "").strip()
            if req_name:
                raw_items_by_exact[req_name] = item
                raw_items_by_casefold[req_name.casefold()] = item

        normalized_evaluations: list[SkillEvaluation] = []
        for idx, expected_req in enumerate(requirements):
            matched_item = raw_items_by_exact.get(expected_req)
            if matched_item is None:
                matched_item = raw_items_by_casefold.get(expected_req.strip().casefold())
            if matched_item is None and idx < len(items) and isinstance(items[idx], dict):
                matched_item = items[idx]

            if matched_item is None:
                raise JudgeProviderError(f"Judge output missing requirement: {expected_req}")
            
            # Handle score alias or satisfaction_percent
            score = matched_item.get("satisfaction_percent")
            if score is None:
                score = matched_item.get("score", 0.0)
            try:
                satisfaction_percent = float(score)
            except (ValueError, TypeError):
                satisfaction_percent = 0.0

            satisfaction_percent = max(0.0, min(100.0, satisfaction_percent))
            
            reasoning = str(matched_item.get("reasoning") or "")
            evidence_quote = str(matched_item.get("evidence_quote") or "")
            
            if evidence_quote:
                normalized_quote = " ".join(evidence_quote.split())
                if not any(normalized_quote in " ".join(ev.split()) for ev in evidence):
                    # If quote does not match candidate evidence, clear it rather than failing
                    evidence_quote = ""

            normalized_evaluations.append(
                SkillEvaluation(
                    requirement=expected_req,
                    satisfaction_percent=satisfaction_percent,
                    reasoning=reasoning,
                    evidence_quote=evidence_quote,
                )
            )
        return normalized_evaluations


class OpenAICompatibleJudgeProvider(JudgeProvider):
    RETRY_DELAYS = (1, 2, 4)

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

    def _call_http(
        self,
        system_prompt: str,
        user_prompt: str,
        req_names: list[str],
        evidence: list[str],
    ) -> JudgeResponse:
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
            "seed": 42,
            "response_format": {"type": "json_object"},
        }
        logger.info(
            "Judge request provider=%s model=%s requirements=%d evidence_items=%d payload_chars=%d",
            self.name,
            self.model,
            len(req_names),
            len(evidence),
            len(json.dumps(payload)),
        )
        try:
            with httpx.Client(timeout=config.JUDGE_TIMEOUT_SECONDS) as client:
                for attempt in range(len(self.RETRY_DELAYS) + 1):
                    response = client.post(
                        f"{self._base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                    if response.status_code not in (429, 503):
                        break
                    if attempt == len(self.RETRY_DELAYS):
                        response.raise_for_status()
                    delay = self.RETRY_DELAYS[attempt]
                    logger.warning(
                        "%s judge returned %s, retrying model=%s in %ss",
                        self.name,
                        response.status_code,
                        self.model,
                        delay,
                    )
                    time.sleep(delay)
                response.raise_for_status()
                body = response.json()
                content = body["choices"][0]["message"]["content"]
            evaluations = self._parse(content, req_names, evidence)
            return JudgeResponse(evaluations, self.name, self.model)
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            raise JudgeProviderError(f"{self.name}/{self.model}: {error}") from error

    def evaluate(self, requirements: list[str], evidence: list[str]) -> JudgeResponse:
        system_prompt, user_prompt = self._messages(requirements, evidence)
        return self._call_http(system_prompt, user_prompt, requirements, evidence)

    def evaluate_semantic(
        self, requirements: list[EnrichedRequirement], evidence: list[str]
    ) -> JudgeResponse:
        system_prompt, user_prompt = self._semantic_messages(requirements, evidence)
        req_names = [r.raw_text for r in requirements]
        return self._call_http(system_prompt, user_prompt, req_names, evidence)


class GeminiJudgeProvider(JudgeProvider):
    GEMINI_RETRY_DELAYS = (1, 2)

    def __init__(self, api_key: str, model: str) -> None:
        self.name = "gemini"
        self.model = self._normalize_model(model)
        self._api_key = api_key

    @classmethod
    def _normalize_model(cls, model: str) -> str:
        candidate = (model or "").strip()
        if not candidate:
            raise JudgeProviderError("Gemini judge model name cannot be empty")
        return candidate

    def _call_gemini_http(
        self,
        system_prompt: str,
        user_prompt: str,
        req_names: list[str],
        evidence: list[str],
    ) -> JudgeResponse:
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": 0.0,
                "seed": 42,
                "responseMimeType": "application/json",
            },
        }
        logger.info(
            "Judge request provider=%s model=%s requirements=%d evidence_items=%d payload_chars=%d",
            self.name,
            self.model,
            len(req_names),
            len(evidence),
            len(json.dumps(payload)),
        )

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent"
        )
        try:
            with httpx.Client(timeout=config.JUDGE_TIMEOUT_SECONDS) as client:
                for attempt in range(len(self.GEMINI_RETRY_DELAYS) + 1):
                    response = client.post(
                        url,
                        headers={"x-goog-api-key": self._api_key},
                        json=payload,
                    )
                    if response.status_code != 503:
                        break
                    if attempt == len(self.GEMINI_RETRY_DELAYS):
                        response.raise_for_status()
                    delay = self.GEMINI_RETRY_DELAYS[attempt]
                    logger.warning(
                        "Gemini judge returned 503, retrying model=%s in %ss",
                        self.model,
                        delay,
                    )
                    time.sleep(delay)
                response.raise_for_status()
                body = response.json()
                content = body["candidates"][0]["content"]["parts"][0]["text"]
            evaluations = self._parse(content, req_names, evidence)
            return JudgeResponse(evaluations, self.name, self.model)
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            raise JudgeProviderError(f"{self.name}/{self.model}: {error}") from error

    def evaluate(self, requirements: list[str], evidence: list[str]) -> JudgeResponse:
        system_prompt, user_prompt = self._messages(requirements, evidence)
        return self._call_gemini_http(system_prompt, user_prompt, requirements, evidence)

    def evaluate_semantic(
        self, requirements: list[EnrichedRequirement], evidence: list[str]
    ) -> JudgeResponse:
        system_prompt, user_prompt = self._semantic_messages(requirements, evidence)
        req_names = [r.raw_text for r in requirements]
        return self._call_gemini_http(system_prompt, user_prompt, req_names, evidence)


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


def _query_single_batch(
    requirements: list[str], evidence: list[str], providers: list[JudgeProvider]
) -> JudgeResponse:
    last_error: Exception | None = None
    for provider in providers:
        try:
            result = provider.evaluate(requirements, evidence)
            logger.info("Judge answered via provider=%s model=%s", result.provider, result.model)
            return result
        except JudgeProviderError as error:
            logger.warning(
                "Judge provider failed provider=%s model=%s error=%s",
                provider.name,
                provider.model,
                error,
            )
            last_error = error
    raise JudgeProviderError(f"All judge providers failed: {last_error}") from last_error


def query_judge(requirements: list[str], evidence: list[str]) -> JudgeResponse:
    assert_clean("\n".join(evidence))
    providers = configured_judge_chain()
    if not providers:
        raise JudgeProviderError("No judge provider is configured")

    # Batch large requirement lists to avoid 413 / 503 payload overflows
    BATCH_SIZE = 10
    if len(requirements) <= BATCH_SIZE:
        return _query_single_batch(requirements, evidence, providers)

    all_evaluations: list[SkillEvaluation] = []
    used_provider = ""
    used_model = ""

    for i in range(0, len(requirements), BATCH_SIZE):
        if i > 0:
            time.sleep(1.0)
        batch_reqs = requirements[i : i + BATCH_SIZE]
        batch_req_set = set(batch_reqs)
        batch_evidence = [
            item
            for item in evidence
            if any(item.startswith(f"Requirement context: {r}\n") for r in batch_req_set)
        ]
        if not batch_evidence:
            batch_evidence = evidence[:30]

        res = _query_single_batch(batch_reqs, batch_evidence, providers)
        all_evaluations.extend(res.evaluations)
        used_provider = res.provider
        used_model = res.model

    return JudgeResponse(
        evaluations=all_evaluations,
        provider=used_provider,
        model=used_model,
    )


def _query_single_batch_semantic(
    requirements: list[EnrichedRequirement], evidence: list[str], providers: list[JudgeProvider]
) -> JudgeResponse:
    last_error: Exception | None = None
    for provider in providers:
        try:
            result = provider.evaluate_semantic(requirements, evidence)
            logger.info("Semantic judge answered via provider=%s model=%s", result.provider, result.model)
            return result
        except JudgeProviderError as error:
            logger.warning(
                "Semantic judge provider failed provider=%s model=%s error=%s",
                provider.name,
                provider.model,
                error,
            )
            last_error = error
    raise JudgeProviderError(f"All judge providers failed: {last_error}") from last_error


def query_semantic_judge(
    requirements: list[EnrichedRequirement], evidence: list[str]
) -> JudgeResponse:
    if not requirements:
        return JudgeResponse(evaluations=[], provider="", model="")
    assert_clean("\n".join(evidence))
    providers = configured_judge_chain()
    if not providers:
        raise JudgeProviderError("No judge provider is configured")

    # In semantic mode, evidence is rendered once per prompt
    SEMANTIC_BATCH_SIZE = 20
    if len(requirements) <= SEMANTIC_BATCH_SIZE:
        return _query_single_batch_semantic(requirements, evidence, providers)

    all_evaluations: list[SkillEvaluation] = []
    used_provider = ""
    used_model = ""

    for i in range(0, len(requirements), SEMANTIC_BATCH_SIZE):
        if i > 0:
            time.sleep(1.0)
        batch_reqs = requirements[i : i + SEMANTIC_BATCH_SIZE]
        res = _query_single_batch_semantic(batch_reqs, evidence, providers)
        all_evaluations.extend(res.evaluations)
        used_provider = res.provider
        used_model = res.model

    return JudgeResponse(
        evaluations=all_evaluations,
        provider=used_provider,
        model=used_model,
    )


