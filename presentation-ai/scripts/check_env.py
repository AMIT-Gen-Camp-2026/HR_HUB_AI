"""Run this before your first `make run` — catches the most common "why isn't this
working" causes before you get a confusing traceback from inside Flask."""
from __future__ import annotations

import sys

from config.settings import get_settings


def main() -> int:
    settings = get_settings()
    problems = []

    if settings.provider == "api" and not settings.gemini_api_key:
        problems.append("PROVIDER=api but GEMINI_API_KEY is empty — set it in .env.")

    if settings.provider == "hf":
        try:
            import sentence_transformers  # noqa: F401
        except ImportError:
            problems.append("PROVIDER=hf but sentence-transformers is not installed — run `make install`.")

    if problems:
        print("Environment check FAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1

    print(f"Environment OK. provider={settings.provider} embedding_model={settings.embedding_model}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
