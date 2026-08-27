"""Map a free-text skill name to a canonical id.

Exact and alias matching first; fuzzy only above a high threshold, because a wrong
canonicalisation silently merges two different skills.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from rapidfuzz import fuzz, process

TAXONOMY = Path(__file__).parent / "taxonomy.yaml"
FUZZY_THRESHOLD = 92


@lru_cache
def _lookup() -> dict[str, str]:
    data = yaml.safe_load(TAXONOMY.read_text(encoding="utf-8"))
    table: dict[str, str] = {}
    for s in data["skills"]:
        table[s["name"].lower()] = s["id"]
        for alias in s.get("aliases", []):
            table[alias.lower()] = s["id"]
    return table


def canonicalise(name: str) -> str | None:
    table = _lookup()
    key = name.strip().lower()
    if key in table:
        return table[key]

    match = process.extractOne(key, table.keys(), scorer=fuzz.WRatio)
    if match and match[1] >= FUZZY_THRESHOLD:
        return table[match[0]]

    # Unknown skill. Return None rather than inventing an id — unknown skills are a
    # signal that the taxonomy needs extending, and that signal should be visible.
    return None
