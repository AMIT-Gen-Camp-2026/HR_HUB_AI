"""CV parsing endpoint. The output is a draft — nothing here writes to a record."""
from __future__ import annotations

from fastapi import APIRouter, File, Request, UploadFile

from app.errors import FeatureDisabled
from app.pipeline.run import run_cv_extraction
from app.schemas.cv import CVExtractionResult
from config.settings import get_features

router = APIRouter(tags=["cv"])


@router.post("/cv/parse", response_model=CVExtractionResult)
async def parse_cv(request: Request, file: UploadFile = File(...)) -> CVExtractionResult:
    if not get_features().cv_parsing:
        raise FeatureDisabled("CV parsing is switched off. Enter the fields manually.")

    return await run_cv_extraction(
        filename=file.filename or "unnamed",
        content=await file.read(),
        provider=request.app.state.provider,
        prompts=request.app.state.prompts,
    )
