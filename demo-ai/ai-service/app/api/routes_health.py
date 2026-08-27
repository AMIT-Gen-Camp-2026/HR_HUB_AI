"""Health. Reports each dependency separately so a failure is diagnosable."""
from __future__ import annotations

from fastapi import APIRouter, Request

from config.settings import get_features, get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request) -> dict:
    settings = get_settings()
    provider_ok = await request.app.state.provider.healthcheck()
    return {
        "status": "ok" if provider_ok else "degraded",
        "provider": {"name": settings.provider, "reachable": provider_ok},
        "prompts_loaded": len(request.app.state.prompts),
        "features": get_features().model_dump(),
        "env": settings.app_env,
    }
