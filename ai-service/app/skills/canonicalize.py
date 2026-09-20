"""Map a free-text skill name to a canonical id.

Exact and alias matching first; fuzzy only above a high threshold, because a wrong
canonicalisation silently merges two different skills.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
import unicodedata

import yaml

TAXONOMY = Path(__file__).parent / "taxonomy.yaml"


def _normalise_key(value: str) -> str:
    """Normalize harmless formatting while preserving meaningful tech symbols."""
    value = unicodedata.normalize("NFKC", value).casefold().strip()
    value = re.sub(r"c\s*#", "csharp", value)
    value = re.sub(r"c\s*\+\s*\+", "cpp", value)
    value = re.sub(r"asp\s*\.\s*net", "aspnet", value)
    value = re.sub(r"\.\s*net\b", "dotnet", value)
    return "".join(character for character in value if character.isalnum())


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


@lru_cache
def _hierarchy_lookup() -> dict[str, set[str]]:
    """Build a mapping from parent canonical ID to all transitive subskill canonical IDs."""
    data = yaml.safe_load(TAXONOMY.read_text(encoding="utf-8"))
    direct: dict[str, set[str]] = {}
    for s in data["skills"]:
        includes = s.get("includes", [])
        if includes:
            direct[s["id"]] = set(includes)

    transitive: dict[str, set[str]] = {}
    for parent in direct:
        visited: set[str] = set()
        queue = list(direct[parent])
        while queue:
            child = queue.pop(0)
            if child not in visited:
                visited.add(child)
                if child in direct:
                    queue.extend(direct[child] - visited)
        transitive[parent] = visited
    return transitive


@lru_cache
def _reverse_hierarchy_lookup() -> dict[str, set[str]]:
    """Build a mapping from child canonical ID to all ancestor parent canonical IDs."""
    hierarchy = _hierarchy_lookup()
    reverse: dict[str, set[str]] = {}
    for parent, children in hierarchy.items():
        for child in children:
            reverse.setdefault(child, set()).add(parent)
    return reverse


def _resolve_canonical_id(skill_or_id: str) -> str | None:
    """Resolve a skill name or ID to its canonical taxonomy ID."""
    if not skill_or_id or not skill_or_id.strip():
        return None
    cleaned = skill_or_id.strip()
    # If already a valid canonical ID in lookup table
    table = _lookup()
    if cleaned in table.values():
        return cleaned
    return canonicalise(cleaned)


def get_encompassed_subskills(skill_or_id: str) -> set[str]:
    """Return all canonical subskill IDs encompassed by the given skill."""
    canonical_id = _resolve_canonical_id(skill_or_id)
    if not canonical_id:
        return set()
    return _hierarchy_lookup().get(canonical_id, set())


def get_parent_skills(skill_or_id: str) -> set[str]:
    """Return all canonical parent skill IDs that encompass the given skill."""
    canonical_id = _resolve_canonical_id(skill_or_id)
    if not canonical_id:
        return set()
    return _reverse_hierarchy_lookup().get(canonical_id, set())


def is_parent_of(parent_skill_or_id: str, child_skill_or_id: str) -> bool:
    """Return True if parent_skill_or_id logically encompasses child_skill_or_id."""
    parent_id = _resolve_canonical_id(parent_skill_or_id)
    child_id = _resolve_canonical_id(child_skill_or_id)
    if not parent_id or not child_id:
        return False
    return child_id in get_encompassed_subskills(parent_id)


def get_encompassed_skills_for_ids(skill_ids: set[str]) -> set[str]:
    """Return union of all encompassed subskill IDs for a set of canonical skill IDs."""
    encompassed: set[str] = set()
    hierarchy = _hierarchy_lookup()
    for sid in skill_ids:
        canonical_id = _resolve_canonical_id(sid)
        if canonical_id and canonical_id in hierarchy:
            encompassed.update(hierarchy[canonical_id])
    return encompassed


def get_parent_skills_for_ids(skill_ids: set[str]) -> set[str]:
    """Return union of all parent/ancestor canonical skill IDs for a set of canonical skill IDs."""
    parents: set[str] = set()
    reverse_hierarchy = _reverse_hierarchy_lookup()
    for sid in skill_ids:
        canonical_id = _resolve_canonical_id(sid)
        if canonical_id and canonical_id in reverse_hierarchy:
            parents.update(reverse_hierarchy[canonical_id])
    return parents


def is_hierarchy_parent(skill_or_id: str) -> bool:
    """Return True if the skill has a non-empty includes: list (is a hierarchy parent)."""
    canonical_id = _resolve_canonical_id(skill_or_id)
    if not canonical_id:
        return False
    return canonical_id in _hierarchy_lookup()


