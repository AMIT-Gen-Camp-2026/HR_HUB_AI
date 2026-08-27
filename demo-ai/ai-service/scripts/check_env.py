"""Verify the selected provider is reachable. Run this before debugging anything else."""
from __future__ import annotations

import asyncio

from app.providers.factory import build_provider
from config.settings import get_features, get_settings


async def main() -> None:
    s = get_settings()
    print(f"PROVIDER = {s.provider}")
    try:
        provider = build_provider(s)
    except Exception as exc:
        print(f"  ✗ could not build provider: {exc}")
        return
    ok = await provider.healthcheck()
    print(f"  {'✓' if ok else '✗'} reachable")
    await provider.aclose()

    print("\nFeature flags:")
    for k, v in get_features().model_dump().items():
        print(f"  {'on ' if v else 'off'}  {k}")


if __name__ == "__main__":
    asyncio.run(main())
