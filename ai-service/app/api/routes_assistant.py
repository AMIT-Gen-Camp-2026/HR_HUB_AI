"""Internal assistant. Data questions run a real filter; policy questions cite a source."""
from __future__ import annotations

from fastapi import APIRouter, Request

from app.errors import FeatureDisabled
from config.settings import get_features

router = APIRouter(tags=["assistant"])


@router.post("/assistant/ask")
async def ask(request: Request, payload: dict) -> dict:
    if not get_features().assistant:
        raise FeatureDisabled("The assistant is switched off. Every filter it wraps is still available.")
    raise NotImplementedError("Sprint 3")
