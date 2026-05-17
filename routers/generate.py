from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel
from typing import Optional
import json

from services.db import get_db, GeneratedContent
from services.ai_service import generate_content

router = APIRouter()

VALID_GEOS = {"ES", "LV", "HR", "LT", "RS"}


class GenerateRequest(BaseModel):
    geo: str
    audience_type: str
    offer: str
    extra: Optional[str] = None
    count: Optional[int] = 5


def validate_geo(geo: str):
    if geo not in VALID_GEOS:
        raise HTTPException(400, f"GEO must be one of: {VALID_GEOS}")


@router.post("/newsletter")
async def gen_newsletter(req: GenerateRequest, db: AsyncSession = Depends(get_db)):
    validate_geo(req.geo)
    result = await generate_content("newsletter", req.geo, req.audience_type, req.offer, db, req.extra or "")
    return {"success": True, "result": result}


@router.post("/subject-lines")
async def gen_subject_lines(req: GenerateRequest, db: AsyncSession = Depends(get_db)):
    validate_geo(req.geo)
    result = await generate_content("subject_lines", req.geo, req.audience_type, req.offer, db)
    return {"success": True, "subject_lines": result}


@router.post("/ab-test")
async def gen_ab_test(req: GenerateRequest, db: AsyncSession = Depends(get_db)):
    validate_geo(req.geo)
    result = await generate_content("ab_test", req.geo, req.audience_type, req.offer, db)
    return {"success": True, "ab_test": result}


@router.post("/ctas")
async def gen_ctas(req: GenerateRequest, db: AsyncSession = Depends(get_db)):
    validate_geo(req.geo)
    result = await generate_content("ctas", req.geo, req.audience_type, req.offer, db)
    return {"success": True, "ctas": result}


@router.get("/history")
async def get_history(
    content_type: Optional[str] = None,
    geo: Optional[str] = None,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    query = select(GeneratedContent).order_by(desc(GeneratedContent.created_at)).limit(limit)
    if content_type:
        query = query.where(GeneratedContent.content_type == content_type)
    if geo:
        query = query.where(GeneratedContent.geo == geo)

    result = await db.execute(query)
    records = result.scalars().all()
    return {
        "history": [
            {
                "id": r.id,
                "content_type": r.content_type,
                "geo": r.geo,
                "audience_type": r.audience_type,
                "prompt_used": r.prompt_used,
                "result": r.result,
                "created_at": r.created_at.isoformat(),
            }
            for r in records
        ]
    }
