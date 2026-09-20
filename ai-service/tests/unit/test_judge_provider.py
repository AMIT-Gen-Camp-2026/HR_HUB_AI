import json
import time
import httpx
import pytest

from app.providers.judge_provider import (
    GeminiJudgeProvider,
    OpenAICompatibleJudgeProvider,
    JudgeProviderError,
    JudgeResponse,
    query_judge,
    query_semantic_judge,
)
from app.schemas.cv import EnrichedRequirement
from config.settings import config


def test_gemini_judge_provider_404_raises_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    # 404 on configured model must raise JudgeProviderError immediately without fallback
    called_urls: list[str] = []

    def fake_post(self, url, **kwargs):
        called_urls.append(str(url))
        request = httpx.Request("POST", url)
        response = httpx.Response(404, request=request, text="Model not found")
        return response

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    provider = GeminiJudgeProvider(api_key="fake-key", model="gemini-3.8-flash")
    with pytest.raises(JudgeProviderError) as exc_info:
        provider.evaluate(["Python"], ["Explicit skill: Python"])

    assert "404" in str(exc_info.value) or "gemini/gemini-3.8-flash" in str(exc_info.value)
    # Confirm it was called for exactly the one configured model URL
    assert len(called_urls) == 1
    assert "gemini-3.8-flash:generateContent" in called_urls[0]


def test_gemini_judge_provider_503_retries_same_model(monkeypatch: pytest.MonkeyPatch) -> None:
    # 503 must retry with backoff on the SAME model
    called_urls: list[str] = []
    sleep_durations: list[float] = []

    monkeypatch.setattr(time, "sleep", lambda s: sleep_durations.append(s))

    attempt_count = 0

    def fake_post(self, url, **kwargs):
        nonlocal attempt_count
        called_urls.append(str(url))
        attempt_count += 1
        request = httpx.Request("POST", url)
        if attempt_count < 3:
            return httpx.Response(503, request=request, text="Service Unavailable")
        # Succeeded on 3rd attempt
        body = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps(
                                    {
                                        "evaluations": [
                                            {
                                                "requirement": "Python",
                                                "satisfaction_percent": 100.0,
                                                "reasoning": "Direct Python skill",
                                                "evidence_quote": "Explicit skill: Python",
                                            }
                                        ]
                                    }
                                )
                            }
                        ]
                    }
                }
            ]
        }
        return httpx.Response(200, request=request, json=body)

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    provider = GeminiJudgeProvider(api_key="fake-key", model="gemini-3.8-flash")
    res = provider.evaluate(["Python"], ["Explicit skill: Python"])

    assert res.provider == "gemini"
    assert res.model == "gemini-3.8-flash"
    assert len(res.evaluations) == 1
    assert res.evaluations[0].satisfaction_percent == 100.0
    # Retried on the SAME model
    assert len(called_urls) == 3
    assert all("gemini-3.8-flash:generateContent" in u for u in called_urls)
    assert sleep_durations == [1, 2]


def test_gemini_judge_provider_returns_exact_configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(self, url, **kwargs):
        request = httpx.Request("POST", url)
        body = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps(
                                    {
                                        "evaluations": [
                                            {
                                                "requirement": "Python",
                                                "satisfaction_percent": 90.0,
                                                "reasoning": "Good Python match",
                                                "evidence_quote": "Explicit skill: Python",
                                            }
                                        ]
                                    }
                                )
                            }
                        ]
                    }
                }
            ]
        }
        return httpx.Response(200, request=request, json=body)

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    provider = GeminiJudgeProvider(api_key="fake-key", model="gemini-3.8-flash")
    res = provider.evaluate(["Python"], ["Explicit skill: Python"])

    assert res.provider == "gemini"
    assert res.model == "gemini-3.8-flash"
    assert res.evaluations[0].requirement == "Python"


# ---------------------------------------------------------------------------
# Semantic Judge Provider Direct Unit Tests (Gap 1)
# ---------------------------------------------------------------------------


def test_gemini_judge_provider_evaluate_semantic_success(monkeypatch: pytest.MonkeyPatch) -> None:
    called_payloads: list[dict] = []

    def fake_post(self, url, **kwargs):
        called_payloads.append(kwargs.get("json", {}))
        request = httpx.Request("POST", url)
        body = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps(
                                    {
                                        "evaluations": [
                                            {
                                                "requirement": "Python 3.10+",
                                                "satisfaction_percent": 95.0,
                                                "reasoning": "Strong Python experience demonstrated",
                                                "evidence_quote": "Explicit skill: Python 3.10+",
                                            }
                                        ]
                                    }
                                )
                            }
                        ]
                    }
                }
            ]
        }
        return httpx.Response(200, request=request, json=body)

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    provider = GeminiJudgeProvider(api_key="fake-gemini-key", model="gemini-3.8-flash")
    reqs = [
        EnrichedRequirement(
            raw_text="Python 3.10+",
            core_intent="Python 3.10+ programming",
        )
    ]
    evidence = ["Explicit skill: Python 3.10+"]
    res = provider.evaluate_semantic(reqs, evidence)

    assert isinstance(res, JudgeResponse)
    assert res.provider == "gemini"
    assert res.model == "gemini-3.8-flash"
    assert len(res.evaluations) == 1
    assert res.evaluations[0].requirement == "Python 3.10+"
    assert res.evaluations[0].satisfaction_percent == 95.0
    assert res.evaluations[0].reasoning == "Strong Python experience demonstrated"
    assert res.evaluations[0].evidence_quote == "Explicit skill: Python 3.10+"
    assert len(called_payloads) == 1
    assert "system_instruction" in called_payloads[0]


def test_openai_compatible_judge_provider_evaluate_semantic_success(monkeypatch: pytest.MonkeyPatch) -> None:
    called_urls: list[str] = []

    def fake_post(self, url, **kwargs):
        called_urls.append(str(url))
        request = httpx.Request("POST", url)
        body = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "evaluations": [
                                    {
                                        "requirement": "PostgreSQL",
                                        "satisfaction_percent": 85.0,
                                        "reasoning": "Solid database experience",
                                        "evidence_quote": "Explicit skill: PostgreSQL",
                                    }
                                ]
                            }
                        )
                    }
                }
            ]
        }
        return httpx.Response(200, request=request, json=body)

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    provider = OpenAICompatibleJudgeProvider(
        name="groq",
        model="llama-3.3-70b-versatile",
        api_key="fake-groq-key",
        base_url="https://api.groq.com/openai/v1",
    )
    reqs = [
        EnrichedRequirement(
            raw_text="PostgreSQL",
            core_intent="PostgreSQL database management",
        )
    ]
    evidence = ["Explicit skill: PostgreSQL"]
    res = provider.evaluate_semantic(reqs, evidence)

    assert isinstance(res, JudgeResponse)
    assert res.provider == "groq"
    assert res.model == "llama-3.3-70b-versatile"
    assert len(res.evaluations) == 1
    assert res.evaluations[0].requirement == "PostgreSQL"
    assert res.evaluations[0].satisfaction_percent == 85.0
    assert res.evaluations[0].reasoning == "Solid database experience"
    assert res.evaluations[0].evidence_quote == "Explicit skill: PostgreSQL"
    assert len(called_urls) == 1
    assert called_urls[0] == "https://api.groq.com/openai/v1/chat/completions"


def test_query_semantic_judge_fallback_gemini_to_groq_on_404(monkeypatch: pytest.MonkeyPatch) -> None:
    # Gemini returns 404 (JudgeProviderError) -> fallback to Groq succeeds
    monkeypatch.setattr(config, "GEMINI_API_KEY", "fake-gemini-key")
    monkeypatch.setattr(config, "GROQ_API_KEY", "fake-groq-key")
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")

    called_urls: list[str] = []

    def fake_post(self, url, **kwargs):
        url_str = str(url)
        called_urls.append(url_str)
        request = httpx.Request("POST", url)
        if "googleapis.com" in url_str:
            return httpx.Response(404, request=request, text="Gemini model not found")
        if "api.groq.com" in url_str:
            body = {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "evaluations": [
                                        {
                                            "requirement": "FastAPI",
                                            "satisfaction_percent": 90.0,
                                            "reasoning": "Groq verified FastAPI experience",
                                            "evidence_quote": "Explicit skill: FastAPI",
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            }
            return httpx.Response(200, request=request, json=body)
        return httpx.Response(500, request=request, text="Unexpected URL")

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    reqs = [
        EnrichedRequirement(
            raw_text="FastAPI",
            core_intent="FastAPI web framework",
        )
    ]
    evidence = ["Explicit skill: FastAPI"]
    res = query_semantic_judge(reqs, evidence)

    assert res.provider == "groq"
    assert res.model == config.GROQ_JUDGE_MODEL
    assert len(res.evaluations) == 1
    assert res.evaluations[0].requirement == "FastAPI"
    assert res.evaluations[0].satisfaction_percent == 90.0
    # Confirmed both Gemini and Groq were called in chain order
    assert len(called_urls) == 2
    assert "googleapis.com" in called_urls[0]
    assert "api.groq.com" in called_urls[1]


def test_query_semantic_judge_fallback_groq_to_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    # Gemini returns 404, Groq returns 500 -> fallback to OpenRouter succeeds
    monkeypatch.setattr(config, "GEMINI_API_KEY", "fake-gemini-key")
    monkeypatch.setattr(config, "GROQ_API_KEY", "fake-groq-key")
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "fake-openrouter-key")

    called_urls: list[str] = []

    def fake_post(self, url, **kwargs):
        url_str = str(url)
        called_urls.append(url_str)
        request = httpx.Request("POST", url)
        if "googleapis.com" in url_str:
            return httpx.Response(404, request=request, text="Gemini unavailable")
        if "api.groq.com" in url_str:
            return httpx.Response(500, request=request, text="Groq internal error")
        if "openrouter.ai" in url_str:
            body = {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "evaluations": [
                                        {
                                            "requirement": "Docker",
                                            "satisfaction_percent": 80.0,
                                            "reasoning": "OpenRouter evaluated Docker",
                                            "evidence_quote": "Explicit skill: Docker",
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            }
            return httpx.Response(200, request=request, json=body)
        return httpx.Response(500, request=request, text="Unexpected URL")

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    reqs = [
        EnrichedRequirement(
            raw_text="Docker",
            core_intent="Docker containerization",
        )
    ]
    evidence = ["Explicit skill: Docker"]
    res = query_semantic_judge(reqs, evidence)

    assert res.provider == "openrouter"
    assert res.model == config.OPENROUTER_JUDGE_MODEL
    assert len(res.evaluations) == 1
    assert res.evaluations[0].requirement == "Docker"
    assert res.evaluations[0].satisfaction_percent == 80.0
    # All 3 providers attempted in chain order
    assert len(called_urls) == 3
    assert "googleapis.com" in called_urls[0]
    assert "api.groq.com" in called_urls[1]
    assert "openrouter.ai" in called_urls[2]


def test_gemini_judge_provider_evaluate_semantic_503_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    # 503 on Gemini evaluate_semantic retries with delays [1, 2]
    called_urls: list[str] = []
    sleep_durations: list[float] = []

    monkeypatch.setattr(time, "sleep", lambda s: sleep_durations.append(s))

    attempt_count = 0

    def fake_post(self, url, **kwargs):
        nonlocal attempt_count
        called_urls.append(str(url))
        attempt_count += 1
        request = httpx.Request("POST", url)
        if attempt_count < 3:
            return httpx.Response(503, request=request, text="Service Unavailable")
        body = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps(
                                    {
                                        "evaluations": [
                                            {
                                                "requirement": "Kubernetes",
                                                "satisfaction_percent": 100.0,
                                                "reasoning": "Kubernetes master",
                                                "evidence_quote": "Explicit skill: Kubernetes",
                                            }
                                        ]
                                    }
                                )
                            }
                        ]
                    }
                }
            ]
        }
        return httpx.Response(200, request=request, json=body)

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    provider = GeminiJudgeProvider(api_key="fake-key", model="gemini-3.8-flash")
    reqs = [
        EnrichedRequirement(
            raw_text="Kubernetes",
            core_intent="Kubernetes container orchestration",
        )
    ]
    evidence = ["Explicit skill: Kubernetes"]
    res = provider.evaluate_semantic(reqs, evidence)

    assert res.provider == "gemini"
    assert res.model == "gemini-3.8-flash"
    assert len(res.evaluations) == 1
    assert res.evaluations[0].satisfaction_percent == 100.0
    assert len(called_urls) == 3
    assert sleep_durations == [1, 2]
    assert sleep_durations == list(GeminiJudgeProvider.GEMINI_RETRY_DELAYS)


def test_openai_compatible_judge_provider_evaluate_semantic_transient_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 429 and 503 on OpenAICompatible evaluate_semantic retries with delays [1, 2, 4]
    called_urls: list[str] = []
    sleep_durations: list[float] = []

    monkeypatch.setattr(time, "sleep", lambda s: sleep_durations.append(s))

    attempt_count = 0

    def fake_post(self, url, **kwargs):
        nonlocal attempt_count
        called_urls.append(str(url))
        attempt_count += 1
        request = httpx.Request("POST", url)
        if attempt_count == 1:
            return httpx.Response(429, request=request, text="Rate Limited")
        if attempt_count == 2:
            return httpx.Response(503, request=request, text="Service Unavailable")
        if attempt_count == 3:
            return httpx.Response(429, request=request, text="Rate Limited")
        body = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "evaluations": [
                                    {
                                        "requirement": "GraphQL",
                                        "satisfaction_percent": 75.0,
                                        "reasoning": "GraphQL evaluated",
                                        "evidence_quote": "Explicit skill: GraphQL",
                                    }
                                ]
                            }
                        )
                    }
                }
            ]
        }
        return httpx.Response(200, request=request, json=body)

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    provider = OpenAICompatibleJudgeProvider(
        name="groq",
        model="llama-3.3-70b-versatile",
        api_key="fake-groq-key",
        base_url="https://api.groq.com/openai/v1",
    )
    reqs = [
        EnrichedRequirement(
            raw_text="GraphQL",
            core_intent="GraphQL API development",
        )
    ]
    evidence = ["Explicit skill: GraphQL"]
    res = provider.evaluate_semantic(reqs, evidence)

    assert res.provider == "groq"
    assert res.model == "llama-3.3-70b-versatile"
    assert len(res.evaluations) == 1
    assert res.evaluations[0].satisfaction_percent == 75.0
    assert len(called_urls) == 4
    assert sleep_durations == [1, 2, 4]
    assert sleep_durations == list(OpenAICompatibleJudgeProvider.RETRY_DELAYS)


def test_query_semantic_judge_all_providers_exhausted_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "GEMINI_API_KEY", "fake-gemini-key")
    monkeypatch.setattr(config, "GROQ_API_KEY", "fake-groq-key")
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "fake-openrouter-key")

    def fake_post(self, url, **kwargs):
        request = httpx.Request("POST", url)
        return httpx.Response(500, request=request, text="Fatal error")

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    reqs = [
        EnrichedRequirement(
            raw_text="Rust",
            core_intent="Rust systems programming",
        )
    ]
    evidence = ["Explicit skill: Rust"]
    with pytest.raises(JudgeProviderError) as exc_info:
        query_semantic_judge(reqs, evidence)

    assert "All judge providers failed" in str(exc_info.value)


def test_query_semantic_judge_batching_exceeds_batch_size(monkeypatch: pytest.MonkeyPatch) -> None:
    # SEMANTIC_BATCH_SIZE is 20. 25 requirements must chunk into 20 and 5, with 1.0s delay.
    monkeypatch.setattr(config, "GEMINI_API_KEY", "fake-gemini-key")
    monkeypatch.setattr(config, "GROQ_API_KEY", "")
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")

    sleep_durations: list[float] = []
    batch_eval_counts: list[int] = []

    monkeypatch.setattr(time, "sleep", lambda s: sleep_durations.append(s))

    def fake_post(self, url, **kwargs):
        request = httpx.Request("POST", url)
        payload = kwargs.get("json", {})
        user_prompt = payload["contents"][0]["parts"][0]["text"]
        
        # Extract requirements JSON array from user prompt to respond with corresponding evaluations
        import re
        match = re.search(r"Requirements:\n(\[.*?\])\n\n<<<CVDATA_PAYLOAD_START>>>", user_prompt, re.DOTALL)
        reqs_data = json.loads(match.group(1)) if match else []
        batch_eval_counts.append(len(reqs_data))
        evaluations = [
            {
                "requirement": item["requirement"],
                "satisfaction_percent": 100.0,
                "reasoning": f"Matched {item['requirement']}",
                "evidence_quote": f"Explicit skill: {item['requirement']}",
            }
            for item in reqs_data
        ]

        body = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps({"evaluations": evaluations})
                            }
                        ]
                    }
                }
            ]
        }
        return httpx.Response(200, request=request, json=body)

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    reqs = [
        EnrichedRequirement(
            raw_text=f"Skill_{i}",
            core_intent=f"Proficiency in Skill_{i}",
        )
        for i in range(25)
    ]
    evidence = [f"Explicit skill: Skill_{i}" for i in range(25)]

    res = query_semantic_judge(reqs, evidence)

    assert isinstance(res, JudgeResponse)
    assert res.provider == "gemini"
    assert res.model == config.GEMINI_JUDGE_MODEL
    assert len(res.evaluations) == 25
    assert [e.requirement for e in res.evaluations] == [f"Skill_{i}" for i in range(25)]
    # Verifies chunking into batch sizes 20 and 5
    assert batch_eval_counts == [20, 5]
    # Verifies 1.0s delay between batches (i > 0)
    assert sleep_durations == [1.0]


def test_query_semantic_judge_empty_requirements_and_no_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    # Empty requirements list returns empty JudgeResponse immediately without calling providers
    res = query_semantic_judge([], ["Some evidence"])
    assert res.evaluations == []
    assert res.provider == ""
    assert res.model == ""

    # No configured providers raises JudgeProviderError
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(config, "GROQ_API_KEY", "")
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")

    reqs = [
        EnrichedRequirement(
            raw_text="Python",
            core_intent="Python programming",
        )
    ]
    with pytest.raises(JudgeProviderError) as exc_info:
        query_semantic_judge(reqs, ["Explicit skill: Python"])

    assert "No judge provider is configured" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Taxonomy Judge Provider & Shared Helper Unit Tests
# ---------------------------------------------------------------------------


def test_openai_compatible_judge_provider_evaluate_taxonomy_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(self, url, **kwargs):
        request = httpx.Request("POST", url)
        body = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "evaluations": [
                                    {
                                        "requirement": "Python",
                                        "satisfaction_percent": 88.0,
                                        "reasoning": "Solid Python",
                                        "evidence_quote": "Explicit skill: Python",
                                    }
                                ]
                            }
                        )
                    }
                }
            ]
        }
        return httpx.Response(200, request=request, json=body)

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    provider = OpenAICompatibleJudgeProvider(
        name="groq",
        model="llama-3.3-70b-versatile",
        api_key="fake-groq-key",
        base_url="https://api.groq.com/openai/v1",
    )
    res = provider.evaluate(["Python"], ["Explicit skill: Python"])
    assert res.provider == "groq"
    assert res.model == "llama-3.3-70b-versatile"
    assert len(res.evaluations) == 1
    assert res.evaluations[0].requirement == "Python"
    assert res.evaluations[0].satisfaction_percent == 88.0


def test_query_judge_taxonomy_fallback_gemini_to_groq(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "GEMINI_API_KEY", "fake-gemini-key")
    monkeypatch.setattr(config, "GROQ_API_KEY", "fake-groq-key")
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")

    called_urls: list[str] = []

    def fake_post(self, url, **kwargs):
        url_str = str(url)
        called_urls.append(url_str)
        request = httpx.Request("POST", url)
        if "googleapis.com" in url_str:
            return httpx.Response(404, request=request, text="Gemini not found")
        if "api.groq.com" in url_str:
            body = {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "evaluations": [
                                        {
                                            "requirement": "Python",
                                            "satisfaction_percent": 92.0,
                                            "reasoning": "Matched Python",
                                            "evidence_quote": "Explicit skill: Python",
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            }
            return httpx.Response(200, request=request, json=body)
        return httpx.Response(500, request=request, text="Unexpected")

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    res = query_judge(["Python"], ["Explicit skill: Python"])
    assert res.provider == "groq"
    assert len(res.evaluations) == 1
    assert res.evaluations[0].requirement == "Python"
    assert len(called_urls) == 2


def test_query_judge_taxonomy_batching(monkeypatch: pytest.MonkeyPatch) -> None:
    # Taxonomy judge BATCH_SIZE is 10. 15 requirements chunk into 10 and 5.
    monkeypatch.setattr(config, "GEMINI_API_KEY", "fake-gemini-key")
    monkeypatch.setattr(config, "GROQ_API_KEY", "")
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")

    batch_counts: list[int] = []
    sleep_durations: list[float] = []

    monkeypatch.setattr(time, "sleep", lambda s: sleep_durations.append(s))

    def fake_post(self, url, **kwargs):
        request = httpx.Request("POST", url)
        payload = kwargs.get("json", {})
        user_prompt = payload["contents"][0]["parts"][0]["text"]
        
        import re
        match = re.search(r"Requirements:\n(\[.*?\])\n\n<<<CVDATA_PAYLOAD_START>>>", user_prompt, re.DOTALL)
        reqs_data = json.loads(match.group(1)) if match else []
        batch_counts.append(len(reqs_data))
        evals = [
            {
                "requirement": item["requirement"],
                "satisfaction_percent": 90.0,
                "reasoning": f"Evidence for {item['requirement']}",
                "evidence_quote": f"Explicit skill: {item['requirement']}",
            }
            for item in reqs_data
        ]
        body = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": json.dumps({"evaluations": evals})}]
                    }
                }
            ]
        }
        return httpx.Response(200, request=request, json=body)

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    reqs = [f"Skill_{i}" for i in range(15)]
    evidence = [f"Requirement context: Skill_{i}\nExplicit skill: Skill_{i}" for i in range(15)]

    res = query_judge(reqs, evidence)
    assert len(res.evaluations) == 15
    assert batch_counts == [10, 5]
    assert sleep_durations == [1.0]


def test_gemini_judge_provider_normalize_model_empty_raises() -> None:
    with pytest.raises(JudgeProviderError) as exc_info:
        GeminiJudgeProvider(api_key="fake", model="   ")
    assert "Gemini judge model name cannot be empty" in str(exc_info.value)


def test_gemini_judge_provider_503_retries_exhausted_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda s: None)

    def fake_post(self, url, **kwargs):
        request = httpx.Request("POST", url)
        return httpx.Response(503, request=request, text="Unavailable")

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    provider = GeminiJudgeProvider(api_key="fake-key", model="gemini-3.8-flash")
    with pytest.raises(JudgeProviderError) as exc_info:
        provider.evaluate(["Python"], ["Explicit skill: Python"])
    assert "503" in str(exc_info.value)


def test_openai_compatible_judge_provider_retries_exhausted_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda s: None)

    def fake_post(self, url, **kwargs):
        request = httpx.Request("POST", url)
        return httpx.Response(429, request=request, text="Too Many Requests")

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    provider = OpenAICompatibleJudgeProvider(
        name="groq",
        model="llama-3.3-70b-versatile",
        api_key="fake-key",
        base_url="https://api.groq.com/openai/v1",
    )
    with pytest.raises(JudgeProviderError) as exc_info:
        provider.evaluate(["Python"], ["Explicit skill: Python"])
    assert "429" in str(exc_info.value)


def test_judge_provider_parse_variations_and_errors() -> None:
    from app.providers.judge_provider import JudgeProvider

    # Case 1: evaluation count mismatch
    with pytest.raises(JudgeProviderError) as exc:
        JudgeProvider._parse(
            json.dumps({"evaluations": [{"requirement": "Python"}]}),
            ["Python", "SQL"],
            ["Evidence"],
        )
    assert "unexpected evaluation count" in str(exc.value)

    # Case 2: item is not dict
    with pytest.raises(JudgeProviderError) as exc:
        JudgeProvider._parse(
            json.dumps({"evaluations": ["not-a-dict"]}),
            ["Python"],
            ["Evidence"],
        )
    assert "evaluation item is not a dictionary" in str(exc.value)

    # Case 3: case folding match and score alias
    raw_json = json.dumps(
        {
            "evaluations": [
                {
                    "requirement": "PYTHON",
                    "score": 95.0,
                    "reasoning": "Matched casing",
                    "evidence_quote": "Quote not in evidence",
                }
            ]
        }
    )
    evals = JudgeProvider._parse(raw_json, ["Python"], ["Candidate has Python skills"])
    assert len(evals) == 1
    assert evals[0].requirement == "Python"
    assert evals[0].satisfaction_percent == 95.0
    assert evals[0].evidence_quote == ""  # Quote cleared because not in candidate evidence

    # Case 4: non-numeric score defaults to 0.0
    raw_json_bad_score = json.dumps(
        {
            "evaluations": [
                {
                    "requirement": "Python",
                    "satisfaction_percent": "invalid-number",
                }
            ]
        }
    )
    evals_bad_score = JudgeProvider._parse(raw_json_bad_score, ["Python"], ["Evidence"])
    assert evals_bad_score[0].satisfaction_percent == 0.0


def test_judge_provider_base_methods_raise_not_implemented() -> None:
    from app.providers.judge_provider import JudgeProvider

    base = JudgeProvider()
    with pytest.raises(NotImplementedError):
        base.evaluate(["Python"], ["Evidence"])
    with pytest.raises(NotImplementedError):
        base.evaluate_semantic([], ["Evidence"])


def test_query_judge_no_providers_and_all_failed_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # No configured providers
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(config, "GROQ_API_KEY", "")
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")

    with pytest.raises(JudgeProviderError) as exc_info:
        query_judge(["Python"], ["Evidence"])
    assert "No judge provider is configured" in str(exc_info.value)

    # All providers fail
    monkeypatch.setattr(config, "GEMINI_API_KEY", "fake-key")

    def fake_post(self, url, **kwargs):
        request = httpx.Request("POST", url)
        return httpx.Response(500, request=request, text="Fatal error")

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    with pytest.raises(JudgeProviderError) as exc_info:
        query_judge(["Python"], ["Evidence"])
    assert "All judge providers failed" in str(exc_info.value)



