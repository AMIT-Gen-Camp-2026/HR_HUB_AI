"""[AI] Academic evidence source — arXiv API (free, no key required).
Same interface as TavilySearchProvider: .search(query, max_results) -> list[dict]
with keys: title, url, content, source_type.
"""
from __future__ import annotations

import logging
import time
import urllib.parse
import xml.etree.ElementTree as ET

import requests

logger = logging.getLogger(__name__)

_ARXIV_API_URL = "http://export.arxiv.org/api/query"
_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_REQUEST_TIMEOUT = 10
_MIN_DELAY_SECONDS = 3.0  # arXiv usage policy: max ~1 request per 3 seconds

_last_call_at: float = 0.0


def _respect_rate_limit() -> None:
    global _last_call_at
    elapsed = time.monotonic() - _last_call_at
    if elapsed < _MIN_DELAY_SECONDS:
        time.sleep(_MIN_DELAY_SECONDS - elapsed)
    _last_call_at = time.monotonic()


class ArxivSearchProvider:
    """Searches arXiv for papers relevant to a claim. No API key required."""

    def __init__(self, settings) -> None:
        self._settings = settings

    def search(self, query: str, max_results: int = 3) -> list[dict]:
        params = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": max_results,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        url = f"{_ARXIV_API_URL}?{urllib.parse.urlencode(params)}"

        _respect_rate_limit()
        try:
            response = requests.get(url, timeout=_REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException:
            logger.warning("arXiv search failed for query %r", query, exc_info=True)
            return []

        try:
            root = ET.fromstring(response.text)
        except ET.ParseError:
            logger.warning("arXiv response could not be parsed for query %r", query)
            return []

        results: list[dict] = []
        for entry in root.findall(f"{_ATOM_NS}entry"):
            title_el = entry.find(f"{_ATOM_NS}title")
            summary_el = entry.find(f"{_ATOM_NS}summary")
            id_el = entry.find(f"{_ATOM_NS}id")
            if title_el is None or id_el is None:
                continue
            results.append({
                "title": " ".join(title_el.text.split()) if title_el.text else "",
                "url": id_el.text.strip() if id_el.text else "",
                "content": " ".join(summary_el.text.split()) if summary_el is not None and summary_el.text else "",
                "source_type": "academic",
            })
        return results