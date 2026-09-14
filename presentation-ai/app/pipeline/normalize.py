"""Content cleaning + Arabic/English normalization. DETERMINISTIC — no AI. Removes
noise that doesn't carry meaning (duplicate lines, empty elements, stray whitespace),
but must NEVER strip anything that could change a claim's meaning — e.g. never strip
numbers, units, or negation words.
"""
from __future__ import annotations

import re
import unicodedata

from app.pipeline.extract_pptx import ExtractedPresentation, SlideContent

# Normalizes visually-identical Arabic letters that come from DIFFERENT Unicode code points.
_ARABIC_NORMALIZE_MAP = str.maketrans({
    "\u0649": "\u064A",  # ALEF MAKSURA (ى) -> YEH (ي)
    "\u06CC": "\u064A",  # FARSI YEH (ی) -> YEH (ي)
    "\u06A9": "\u0643",  # KEHEH / Persian Kaf (ک) -> ARABIC KAF (ك)
})


def _clean_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_ARABIC_NORMALIZE_MAP)
    text = re.sub(r"[ \t]+", " ", text).strip()
    return text


def normalize(extracted: ExtractedPresentation) -> ExtractedPresentation:
    for slide in extracted.slides:
        seen: set[str] = set()
        kept = []
        for el in slide.elements:
            cleaned = _clean_text(el.content)
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            el.content = cleaned
            kept.append(el)
        slide.elements = kept
        if slide.title:
            slide.title = _clean_text(slide.title)
    return extracted


def slide_to_prompt_text(slide: SlideContent) -> str:
    """Flattens one slide's elements into the plain text block the prompt expects."""
    lines = []
    if slide.title:
        lines.append(f"[Title] {slide.title}")
    for el in slide.elements:
        if el.type == "table":
            prefix = "[Table]"
        elif el.type == "note":
            prefix = "[Speaker Note]"
        elif el.type == "chart":
            prefix = "[Chart]"
        else:
            prefix = "[Text]"
        lines.append(f"{prefix} {el.content}")
    return "\n".join(lines)