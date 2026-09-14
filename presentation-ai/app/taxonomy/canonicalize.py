"""Maps free-text property names ('acc', 'Accuracy', 'accuracy rate') to one canonical
id defined in claim_taxonomy.yaml. Deterministic, rule-based lookup — NOT an LLM call.
If this can't find a match, it returns the original string unchanged rather than
guessing; a claim with an uncanonicalized property is still valid, it just won't
match cleanly against a future Demo AI claim.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

TAXONOMY_PATH = Path(__file__).parent / "claim_taxonomy.yaml"


@lru_cache(maxsize=1)
def _load_taxonomy() -> dict:
    return yaml.safe_load(TAXONOMY_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _alias_lookup() -> dict[str, str]:
    taxonomy = _load_taxonomy()
    lookup: dict[str, str] = {}
    for canonical, spec in taxonomy["properties"].items():
        lookup[canonical.lower()] = canonical
        for alias in spec.get("aliases", []):
            lookup[alias.lower()] = canonical
    return lookup


def canonicalize_property(raw: str) -> str:
    """'Accuracy Rate' -> 'accuracy'. Unknown input is returned as-is (lowercased,
    stripped) rather than raising — canonicalization is a best-effort enrichment,
    never a hard requirement for a claim to be valid."""
    key = raw.strip().lower()
    return _alias_lookup().get(key, key)


def canonical_unit(property_id: str) -> str | None:
    return _load_taxonomy()["properties"].get(property_id, {}).get("unit")


def is_known_claim_type(claim_type: str) -> bool:
    return claim_type in _load_taxonomy()["claim_types"]