from __future__ import annotations

from app.pipeline.normalize import normalise


def test_alef_forms_unify() -> None:
    assert normalise("أحمد") == normalise("احمد") == normalise("إحمد")


def test_arabic_digits_become_latin() -> None:
    assert "2026" in normalise("سنة ٢٠٢٦")


def test_diacritics_removed() -> None:
    assert normalise("مُحَمَّد") == normalise("محمد")
