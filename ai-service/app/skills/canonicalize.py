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
