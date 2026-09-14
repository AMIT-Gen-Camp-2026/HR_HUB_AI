"""Probe Google Search grounding availability without printing secrets.

Reports only: provider name, whether an API key is configured, and a sanitized
error class/message from one grounded generate_content call.
"""
from __future__ import annotations

from config.settings import Settings


def _quota_fields(exc: Exception) -> dict:
    details = getattr(exc, "details", None)
    found: dict = {}
    stack = [details]
    while stack:
        obj = stack.pop()
        if isinstance(obj, dict):
            for key in ("quotaValue", "quotaMetric", "quotaId", "retryDelay"):
                if key in obj and key not in found:
                    found[key] = obj[key]
            stack.extend(obj.values())
        elif isinstance(obj, list):
            stack.extend(obj)
    return found
    lowered = text.lower()
    for token in ("key", "token", "bearer", "sk-"):
        if token in lowered and len(text) > 80:
            return text[:80] + " ...[redacted]"
    return text[:500]


def main() -> None:
    settings = Settings()
    print(f"provider={settings.provider}")
    print(f"gemini_model={settings.gemini_model}")
    print(f"feature_web_grounding={settings.feature_web_grounding}")
    print(f"gemini_api_key_configured={bool(settings.gemini_api_key)}")

    if settings.provider != "api" or not settings.gemini_api_key:
        print("grounding_probe=skipped (PROVIDER is not api or no API key)")
        return

    import time
    from google import genai

    client = genai.Client(api_key=settings.gemini_api_key)

    try:
        plain = client.models.generate_content(
            model=settings.gemini_model,
            contents="Reply with the single word OK.",
        )
        print(f"plain_generate=ok chars={len(plain.text or '')}")
    except Exception as exc:
        print(f"plain_generate=error type={type(exc).__name__} code={getattr(exc, 'code', None)}")
        print(f"plain_generate_message={_sanitize(str(exc))}")
        print(f"plain_quota_fields={_quota_fields(exc)}")

    time.sleep(4)

    try:
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents="Using Google Search, confirm whether PostgreSQL supports JSON columns. Reply with one short sentence.",
            config={"tools": [{"google_search": {}}]},
        )
        sources = []
        for candidate in getattr(response, "candidates", None) or []:
            metadata = getattr(candidate, "grounding_metadata", None)
            chunks = getattr(metadata, "grounding_chunks", None) or [] if metadata else []
            for chunk in chunks:
                web = getattr(chunk, "web", None)
                if web and getattr(web, "uri", None):
                    sources.append("present")
        print("grounding_probe=ok")
        print(f"grounding_sources_found={len(sources)}")
        print(f"response_chars={len((response.text or ''))}")
    except Exception as exc:
        print(f"grounding_probe=error")
        print(f"error_type={type(exc).__name__}")
        print(f"error_code={getattr(exc, 'code', None)}")
        print(f"error_status={getattr(exc, 'status', None)}")
        print(f"error_message={_sanitize(str(exc))}")
        print(f"quota_fields={_quota_fields(exc)}")


if __name__ == "__main__":
    main()
