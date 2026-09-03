from __future__ import annotations

from app.skills.canonicalize import canonicalise, extract_explicit_skills


def test_aliases_map_to_one_id() -> None:
    assert canonicalise("Scikit-learn") == canonicalise("sklearn") == canonicalise("scikit learn")


def test_unknown_skill_returns_none() -> None:
    assert canonicalise("Underwater Basket Weaving") is None


def test_ai_domain_aliases_are_explicit_and_conservative() -> None:
    assert canonicalise("ChatGPT") == canonicalise("Chat GPT")
    assert canonicalise("Gemini") == canonicalise("Google Gemini")
    assert canonicalise("AI Studio") == canonicalise("Google AI Studio")
    assert canonicalise("Firefly") == canonicalise("Adobe Firefly")
    assert canonicalise("Runway") == canonicalise("Runway ML")
    assert canonicalise("ChatGPT Image Generation") == canonicalise(
        "chatgpt image generation"
    )
    assert canonicalise("AI") is None


def test_extract_explicit_skills_returns_canonical_display_names() -> None:
    skills = extract_explicit_skills("ChatGPT, Google Gemini, Runway ML, AI-powered marketing")

    assert "ChatGPT" in skills
    assert "Gemini" in skills
    assert "Runway" in skills


def test_explicit_skill_scan_uses_word_boundaries() -> None:
    assert "AI" not in extract_explicit_skills("Air Canada")
    assert "ChatGPT" in extract_explicit_skills("Used ChatGPT for training")
