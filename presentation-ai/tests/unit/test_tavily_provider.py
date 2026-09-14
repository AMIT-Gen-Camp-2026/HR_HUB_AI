from unittest.mock import MagicMock

import requests

from app.providers.search.tavily_provider import TavilySearchProvider
from config.settings import Settings


def _provider() -> TavilySearchProvider:
    return TavilySearchProvider(Settings(tavily_api_key="test-key"))


def test_search_returns_normalized_results(monkeypatch):
    response = MagicMock()
    response.json.return_value = {"results": [{
        "title": "Example", "url": "https://example.com", "content": "Useful snippet", "score": 0.9,
    }]}
    monkeypatch.setattr("app.providers.search.tavily_provider.requests.post", lambda *_, **__: response)

    results = _provider().search("example query", max_results=3)

    assert results == [{"title": "Example", "url": "https://example.com", "content": "Useful snippet"}]


def test_search_returns_empty_list_for_empty_results(monkeypatch, caplog):
    response = MagicMock()
    response.json.return_value = {"results": []}
    monkeypatch.setattr("app.providers.search.tavily_provider.requests.post", lambda *_, **__: response)

    assert _provider().search("example query") == []
    assert "no usable results" in caplog.text


def test_search_handles_http_errors_and_timeouts(monkeypatch, caplog):
    monkeypatch.setattr(
        "app.providers.search.tavily_provider.requests.post",
        MagicMock(side_effect=requests.Timeout("timed out")),
    )

    assert _provider().search("example query") == []
    assert "Tavily search failed" in caplog.text
