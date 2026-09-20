"""
app/pipeline/jd_enrichment.py

Enriches structured job description requirement strings using LLM analysis.
Produces an EnrichedJobDescription containing EnrichedRequirement objects.
Implements in-memory LRU caching per requirement string with batched LLM calls.
"""
from __future__ import annotations

from collections import OrderedDict
import hashlib
import json
import logging
import time

from app.pipeline.postprocess import extract_json_from_model_output
from app.pipeline.redact import assert_clean, redact
from app.prompts.registry import build_jd_enrichment_batch_prompt
from app.providers.hf_provider import _build_model_chain, query_model
from app.schemas.cv import EnrichedJobDescription, EnrichedRequirement, JobDescription
from config.settings import config

logger = logging.getLogger(__name__)

JD_ENRICHMENT_PROMPT_VERSION = "jd-enrichment-v2"
JD_ENRICHMENT_SCHEMA_VERSION = "enriched-requirement-v1"
ENRICHMENT_CACHE_TTL_SECONDS = 3600.0
ENRICHMENT_CACHE_MAX_ENTRIES = 256
ENRICHMENT_BATCH_SIZE = 20

_jd_enrichment_cache: OrderedDict[str, tuple[float, EnrichedRequirement]] = OrderedDict()


class JDEnrichmentError(Exception):
    """Raised when enriching job requirement strings fails."""
    pass


def _jd_requirement_cache_key(requirement_text: str) -> str:
    """Builds a deterministic SHA-256 cache key for a requirement string."""
    configuration = {
        "requirement_hash": hashlib.sha256(requirement_text.strip().encode("utf-8")).hexdigest(),
        "prompt_version": JD_ENRICHMENT_PROMPT_VERSION,
        "schema_version": JD_ENRICHMENT_SCHEMA_VERSION,
        "models": _build_model_chain(),
    }
    return hashlib.sha256(
        json.dumps(configuration, sort_keys=True).encode("utf-8")
    ).hexdigest()


def get_cached_requirement(cache_key: str) -> EnrichedRequirement | None:
    entry = _jd_enrichment_cache.get(cache_key)
    if entry is None:
        return None
    created_at, payload = entry
    ttl = getattr(config, "CACHE_TTL_SECONDS", ENRICHMENT_CACHE_TTL_SECONDS)
    if time.monotonic() - created_at >= ttl:
        del _jd_enrichment_cache[cache_key]
        return None
    _jd_enrichment_cache.move_to_end(cache_key)
    return payload


def store_cached_requirement(cache_key: str, payload: EnrichedRequirement) -> None:
    _jd_enrichment_cache[cache_key] = (time.monotonic(), payload)
    _jd_enrichment_cache.move_to_end(cache_key)
    max_entries = getattr(config, "CACHE_MAX_ENTRIES", ENRICHMENT_CACHE_MAX_ENTRIES)
    while len(_jd_enrichment_cache) > max_entries:
        _jd_enrichment_cache.popitem(last=False)


def clear_jd_enrichment_cache() -> None:
    """Resets the in-memory enrichment cache."""
    _jd_enrichment_cache.clear()


def parse_and_validate_enriched_batch(
    raw_output: str, expected_requirements: list[str]
) -> list[EnrichedRequirement]:
    """
    Parses model JSON batch output and validates each item into an EnrichedRequirement.
    Enforces exact item count matching expected input requirements.
    """
    payload = extract_json_from_model_output(raw_output)
    if not isinstance(payload, dict):
        raise ValueError(f"Model output did not produce a valid JSON object for: {expected_requirements}")

    items = payload.get("requirements")
    if not isinstance(items, list) or len(items) != len(expected_requirements):
        raise ValueError(
            f"Model returned {len(items) if isinstance(items, list) else type(items)} items, "
            f"expected {len(expected_requirements)} for requirements: {expected_requirements}"
        )

    enriched_items: list[EnrichedRequirement] = []
    for idx, (data, expected_raw_text) in enumerate(zip(items, expected_requirements)):
        if not isinstance(data, dict):
            raise ValueError(f"Item at index {idx} is not a JSON object for requirement '{expected_raw_text}'")

        # Unconditionally overwrite raw_text with the original requirement string
        data["raw_text"] = expected_raw_text

        spec = str(data.get("specificity", "specific")).lower().strip()
        data["specificity"] = "vague" if spec == "vague" else "specific"

        components = data.get("implied_components")
        if not isinstance(components, list):
            data["implied_components"] = [str(components)] if components else []
        else:
            data["implied_components"] = [str(c).strip() for c in components if str(c).strip()]

        data["is_composite"] = bool(data.get("is_composite", False))

        if not data.get("core_intent"):
            data["core_intent"] = expected_raw_text

        enriched_items.append(EnrichedRequirement(**data))

    return enriched_items


def _enrich_batch_misses(misses: list[str]) -> dict[str, EnrichedRequirement]:
    """
    Enriches a batch of cache-miss requirement strings in chunked LLM calls.
    Requirements are sorted deterministically before chunking.
    """
    if not misses:
        return {}

    sorted_misses = sorted(misses, key=lambda s: (s.casefold(), s))
    results: dict[str, EnrichedRequirement] = {}

    for i in range(0, len(sorted_misses), ENRICHMENT_BATCH_SIZE):
        chunk = sorted_misses[i : i + ENRICHMENT_BATCH_SIZE]
        redacted_chunk = [redact(req)[0] for req in chunk]
        system_prompt, user_prompt = build_jd_enrichment_batch_prompt(redacted_chunk)
        assert_clean(system_prompt + user_prompt)

        def validator(raw_output: str) -> list[EnrichedRequirement]:
            return parse_and_validate_enriched_batch(raw_output, chunk)

        try:
            enriched_chunk = query_model(system_prompt, user_prompt, validate_fn=validator)
            if not isinstance(enriched_chunk, list):
                raise ValueError(f"Expected list of EnrichedRequirement, got {type(enriched_chunk)}")

            for original_req, enriched_req in zip(chunk, enriched_chunk):
                cache_key = _jd_requirement_cache_key(original_req.strip())
                store_cached_requirement(cache_key, enriched_req)
                results[original_req.strip()] = enriched_req
        except Exception as e:
            logger.error("Failed to enrich requirements batch %s: %s", chunk, e)
            raise JDEnrichmentError(
                f"Failed to enrich requirements batch {chunk}: {e}"
            ) from e

    return results


def extract_jd_requirements(
    jd: JobDescription,
) -> EnrichedJobDescription:
    """
    Enriches all required and nice-to-have skill requirements in a JobDescription.
    Dedupes identical requirement strings and evaluates all cache misses in a single batched call
    (or chunked if > ENRICHMENT_BATCH_SIZE).
    """
    grouped_skills: list[str] = [
        skill for group in (jd.required_skill_groups or []) for skill in group
    ]
    all_requirements: list[str] = (
        list(jd.required_skills) + grouped_skills + list(jd.nice_to_have_skills)
    )

    unique_reqs: dict[str, str] = {}
    for req in all_requirements:
        cleaned = req.strip()
        if cleaned and cleaned not in unique_reqs:
            unique_reqs[cleaned] = req

    enriched_by_key: dict[str, EnrichedRequirement] = {}
    cache_misses: list[str] = []

    for cleaned_key, original_req in unique_reqs.items():
        cache_key = _jd_requirement_cache_key(cleaned_key)
        cached = get_cached_requirement(cache_key)
        if cached is not None:
            enriched_by_key[cleaned_key] = cached
        else:
            cache_misses.append(original_req)

    if cache_misses:
        newly_enriched = _enrich_batch_misses(cache_misses)
        enriched_by_key.update(newly_enriched)

    def _build_enriched(req: str) -> EnrichedRequirement:
        cleaned = req.strip()
        if cleaned in enriched_by_key:
            return enriched_by_key[cleaned]
        return EnrichedRequirement(
            raw_text=req,
            core_intent=req,
            implied_components=[],
            is_composite=False,
            specificity="specific",
        )

    enriched_required: list[EnrichedRequirement] = [
        _build_enriched(req) for req in jd.required_skills
    ]

    enriched_skill_groups: list[list[EnrichedRequirement]] | None = None
    if jd.required_skill_groups is not None:
        enriched_skill_groups = [
            [_build_enriched(req) for req in group]
            for group in jd.required_skill_groups
        ]

    enriched_nice_to_have: list[EnrichedRequirement] = [
        _build_enriched(req) for req in jd.nice_to_have_skills
    ]

    return EnrichedJobDescription(
        job_description=jd,
        required_skills=enriched_required,
        required_skill_groups=enriched_skill_groups,
        nice_to_have_skills=enriched_nice_to_have,
    )


