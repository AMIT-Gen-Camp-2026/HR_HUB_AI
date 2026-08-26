"""Ranking. Orders a queue — it never removes anyone from it."""
from __future__ import annotations

from fastapi import APIRouter, Request

from app.errors import FeatureDisabled
from app.schemas.cv import RankingRequest, RankingResult
from config.settings import get_features

router = APIRouter(tags=["ranking"])


@router.post("/rank", response_model=RankingResult)
async def rank(request: Request, payload: RankingRequest) -> RankingResult:
    if not get_features().ranking:
        raise FeatureDisabled("Ranking is switched off. The queue falls back to submission order.")
    raise NotImplementedError("Sprint 2 — see app/pipeline/ranking.py")
