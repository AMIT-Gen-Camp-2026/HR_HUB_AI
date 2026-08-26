from __future__ import annotations

from app.skills.canonicalize import canonicalise


def test_aliases_map_to_one_id() -> None:
    assert canonicalise("Scikit-learn") == canonicalise("sklearn") == canonicalise("scikit learn")


def test_unknown_skill_returns_none() -> None:
    assert canonicalise("Underwater Basket Weaving") is None
