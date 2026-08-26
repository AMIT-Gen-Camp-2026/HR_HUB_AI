"""The schema IS the contract. These tests fail when the contract changes."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.cv import CVExtraction, Evidence, Skill


def test_skill_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        Skill(name="Pandas", source="inferred", confidence=0.9)  # type: ignore[call-arg]


def test_confidence_is_bounded() -> None:
    with pytest.raises(ValidationError):
        Skill(
            name="Pandas",
            source="inferred",
            evidence=Evidence(section="projects", span="using Pandas"),
            confidence=1.4,
        )


def test_duplicate_skills_are_collapsed() -> None:
    ev = Evidence(section="skills", span="Python")
    x = CVExtraction(
        personal={"full_name": "T"},
        skills=[
            Skill(name="Python", canonical_id="skill.python", source="explicit", evidence=ev, confidence=1.0),
            Skill(name="python", canonical_id="skill.python", source="inferred", evidence=ev, confidence=0.9),
        ],
    )
    assert len(x.skills) == 1
