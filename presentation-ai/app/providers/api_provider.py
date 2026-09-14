"""Real Gemini backend. This is the ONLY file in the project allowed to import
google.genai directly (docs/DECISIONS.md section 6 / BUILD_TASKS.md tech-stack rule).
Everything else talks to this through app/providers/base.py's ProviderAdapter contract.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.errors import DailyQuotaExceeded
from app.providers.base import CompletionResult, ProviderAdapter
from config.settings import Settings

logger = logging.getLogger(__name__)

# Google's free-tier Flash models occasionally return 503 UNAVAILABLE under high demand.
_SERVER_ERROR_RETRIES = 2
_SERVER_ERROR_BACKOFF_SECONDS = 2.0

# Process-wide pacing clock between actual Gemini API calls.
_last_gemini_call_at: float = 0.0
_RPM_RETRY_DELAY_CAP_SECONDS = 60.0


def wait_for_gemini_pacing(pacing_seconds: float) -> None:
    """Block until `pacing_seconds` have elapsed since the previous Gemini call
    in this process. The first call after process start does not wait."""
    global _last_gemini_call_at
    if pacing_seconds <= 0:
        _last_gemini_call_at = time.monotonic()
        return
    now = time.monotonic()
    if _last_gemini_call_at > 0:
        remaining = pacing_seconds - (now - _last_gemini_call_at)
        if remaining > 0:
            time.sleep(remaining)
    _last_gemini_call_at = time.monotonic()


def _iter_dicts(obj):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _iter_dicts(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_dicts(item)


def parse_retry_delay_seconds(details) -> float | None:
    """Extract Google's retryDelay (e.g. '8s') from a ClientError.details payload."""
    for item in _iter_dicts(details):
        retry_delay = item.get("retryDelay")
        if isinstance(retry_delay, str) and retry_delay.endswith("s"):
            try:
                return float(retry_delay[:-1])
            except ValueError:
                continue
        if isinstance(retry_delay, (int, float)):
            return float(retry_delay)
    return None


def quota_debug_fields(details) -> dict:
    """Pull quotaValue / quotaMetric / retryDelay for logs."""
    found: dict = {}
    for item in _iter_dicts(details):
        for key in ("quotaValue", "quotaMetric", "quotaId", "retryDelay"):
            if key in item and key not in found:
                found[key] = item[key]
    return found


class GeminiProvider(ProviderAdapter):
    name = "api"

    def __init__(self, settings: Settings) -> None:
        if not settings.gemini_api_key:
            raise RuntimeError(
                "PROVIDER=api requires GEMINI_API_KEY to be set in the environment/.env file."
            )
        self._settings = settings
        self._client = genai.Client(api_key=settings.gemini_api_key)

    def model_for_completion(self, *, use_grounding: bool = False) -> str:
        """Select the configured Google Search-capable model only for grounding."""
        if use_grounding:
            return self._settings.gemini_grounding_model
        return self._settings.gemini_model

    def complete(
        self,
        *,
        prompt: str,
        response_schema: Any | None = None,
        use_grounding: bool = False,
        temperature: float = 0.2,
    ) -> CompletionResult:
        model = self.model_for_completion(use_grounding=use_grounding)
        if use_grounding:
            config = types.GenerateContentConfig(
                temperature=temperature,
                tools=[{"google_search": {}}],
            )
        elif response_schema is not None:
            config = types.GenerateContentConfig(
                temperature=temperature,
                response_mime_type="application/json",
                response_schema=response_schema,
            )
        else:
            config = types.GenerateContentConfig(
                temperature=temperature,
            )

        last_server_error: genai_errors.ServerError | None = None
        rpm_retried = False
        server_attempts = 0

        while True:
            try:
                wait_for_gemini_pacing(self._settings.gemini_call_pacing_seconds)
                response = self._client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=config,
                )
                break
            except genai_errors.ClientError as exc:
                if getattr(exc, "code", None) == 429 or "RESOURCE_EXHAUSTED" in str(exc):
                    details = getattr(exc, "details", None)
                    debug = quota_debug_fields(details)
                    retry_after = parse_retry_delay_seconds(details)
                    logger.warning(
                        "Gemini 429 RESOURCE_EXHAUSTED | quota_fields=%s | retryDelay=%s | grounding=%s",
                        debug, retry_after, use_grounding,
                    )
                    if (
                        not rpm_retried
                        and retry_after is not None
                        and 0 < retry_after <= _RPM_RETRY_DELAY_CAP_SECONDS
                    ):
                        rpm_retried = True
                        time.sleep(retry_after)
                        continue
                    raise DailyQuotaExceeded(
                        "Gemini free-tier daily/rate quota exceeded. Try again later or switch to a paid tier."
                    ) from exc
                raise
            except genai_errors.ServerError as exc:
                last_server_error = exc
                if server_attempts < _SERVER_ERROR_RETRIES:
                    server_attempts += 1
                    logger.warning(
                        "Gemini server error (attempt %d/%d), retrying in %.1fs",
                        server_attempts, _SERVER_ERROR_RETRIES, _SERVER_ERROR_BACKOFF_SECONDS,
                    )
                    time.sleep(_SERVER_ERROR_BACKOFF_SECONDS)
                    continue
                logger.warning(
                    "Gemini server error persisted after retries, treating as empty completion",
                    exc_info=last_server_error,
                )
                return CompletionResult(text="", model_version=model)

        text = (response.text or "").strip()
        grounding_sources = self._extract_grounding_sources(response)
        usage = getattr(response, "usage_metadata", None)

        return CompletionResult(
            text=text,
            model_version=model,
            tokens_in=getattr(usage, "prompt_token_count", 0) or 0,
            tokens_out=getattr(usage, "candidates_token_count", 0) or 0,
            grounding_sources=grounding_sources,
        )

    @staticmethod
    def _extract_grounding_sources(response) -> list[dict]:
        sources: list[dict] = []
        try:
            candidates = response.candidates or []
            for candidate in candidates:
                metadata = getattr(candidate, "grounding_metadata", None)
                if not metadata:
                    continue
                chunks = getattr(metadata, "grounding_chunks", None) or []
                for chunk in chunks:
                    web = getattr(chunk, "web", None)
                    if web and getattr(web, "uri", None):
                        sources.append({
                            "url": web.uri,
                            "title": getattr(web, "title", "") or "",
                        })
        except Exception:
            logger.warning("Failed to parse grounding metadata - returning no sources", exc_info=True)
            return []
        return sources

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            wait_for_gemini_pacing(self._settings.gemini_call_pacing_seconds)
            response = self._client.models.embed_content(
                model=self._settings.gemini_embedding_model,
                contents=texts,
            )
        except genai_errors.ClientError as exc:
            if getattr(exc, "code", None) == 429 or "RESOURCE_EXHAUSTED" in str(exc):
                details = getattr(exc, "details", None)
                logger.warning(
                    "Gemini embed 429 RESOURCE_EXHAUSTED | quota_fields=%s",
                    quota_debug_fields(details),
                )
                raise DailyQuotaExceeded(
                    "Gemini free-tier daily/rate quota exceeded. Try again later or switch to a paid tier."
                ) from exc
            raise
        return [list(e.values) for e in response.embeddings]
