"""Tavily-backed web search for objective-claim evidence."""
from __future__ import annotations

import logging

import requests

from config.settings import Settings

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://api.tavily.com/search"
_TIMEOUT_SECONDS = 15


class TavilySearchProvider:
    """Minimal Tavily client that deliberately degrades to no search results."""

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.tavily_api_key

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        if not self._api_key:
            logger.warning("Tavily search unavailable: TAVILY_API_KEY is not configured")
            return []

        try:
            response = requests.post(
                _SEARCH_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"query": query, "max_results": max_results, "search_depth": "basic"},
                timeout=_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            raw_results = response.json().get("results", [])
        except (requests.RequestException, ValueError, TypeError) as exc:
            logger.warning("Tavily search failed: %s", exc)
            return []

        if not isinstance(raw_results, list):
            logger.warning("Tavily search returned an invalid results payload")
            return []

        results: list[dict] = []
        for item in raw_results:
            if not isinstance(item, dict) or not item.get("url"):
                continue
            results.append({
                "title": str(item.get("title") or ""),
                "url": str(item["url"]),
                "content": str(item.get("content") or ""),
            })
        if not results:
            logger.warning("Tavily search returned no usable results")
        return results
