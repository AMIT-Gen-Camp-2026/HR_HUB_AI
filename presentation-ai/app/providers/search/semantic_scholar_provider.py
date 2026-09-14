"""[AI] Academic evidence source — OpenAlex API (free, no key required, no email
domain restrictions — unlike Semantic Scholar which now blocks free-domain emails).
Class name kept as SemanticScholarProvider so no other file needs to change.
Same interface as TavilySearchProvider: .search(query, max_results) -> list[dict]
with keys: title, url, content, source_type.
"""
from __future__ import annotations

import logging
from wsgiref import headers

import requests

logger = logging.getLogger(__name__)

_OPENALEX_API_URL = "https://api.openalex.org/works"
_REQUEST_TIMEOUT = 10
# OpenAlex gives faster/higher rate limits ("polite pool") to requests that
# identify a contact email in the User-Agent — no signup needed, just courtesy.
_CONTACT_EMAIL = "youssefkhaled855@gmail.com"  # TODO: replace with a real contact email

import time

_last_call_at: float = 0.0
_MIN_DELAY_SECONDS = 1.0


def _respect_rate_limit() -> None:
    global _last_call_at
    elapsed = time.monotonic() - _last_call_at
    if elapsed < _MIN_DELAY_SECONDS:
        time.sleep(_MIN_DELAY_SECONDS - elapsed)
    _last_call_at = time.monotonic()
    
class SemanticScholarProvider:
    """Searches OpenAlex for academic works relevant to a claim. No API key required."""

    def __init__(self, settings) -> None:
        self._settings = settings

    def search(self, query: str, max_results: int = 3) -> list[dict]:
        params = {
            "search": query,
            "per-page": max_results,
        }
        headers = {"User-Agent": f"presentation-ai (mailto:{_CONTACT_EMAIL})"}
        _respect_rate_limit()
        try:
            response = requests.get(_OPENALEX_API_URL, params=params, headers=
            headers, timeout=_REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException:
            logger.warning("OpenAlex search failed for query %r", query, exc_info=True)
            return []

        try:
            data = response.json()
        except ValueError:
            logger.warning("OpenAlex response could not be parsed for query %r", query)
            return []

        results: list[dict] = []
        for work in data.get("results", []):
            abstract = _reconstruct_abstract(work.get("abstract_inverted_index"))
            if not abstract:
                continue
            results.append({
                "title": work.get("title") or work.get("display_name") or "",
                "url": work.get("doi") or work.get("id") or "",
                "content": abstract,
                "source_type": "academic",
            })
        return results


def _reconstruct_abstract(inverted_index: dict | None) -> str:
    """OpenAlex returns abstracts as an inverted index ({word: [positions]}) instead
    of plain text (due to publisher copyright restrictions on redistributing full
    abstract text). Rebuild the plain-text order from the positions."""
    if not inverted_index:
        return ""
    positions: dict[int, str] = {}
    for word, idxs in inverted_index.items():
        for idx in idxs:
            positions[idx] = word
    return " ".join(positions[i] for i in sorted(positions))