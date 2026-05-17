from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel, field_validator
from typing import Optional
import json

from services.db import get_db, GeneratedContent
from services.ai_service import generate_content
from services.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)

VALID_GEOS = {"ES", "LV", "HR", "LT", "RS"}
VALID_AUDIENCES = {"Casino", "Sportsbook", "VIP", "Casino VIP", "General"}


class GenerateRequest(BaseModel):
    geo: str
    audience_type: str
    offer: str
    extra: Optional[str] = None
    count: Optional[int] = 5

    @field_validator("geo")
    @classmethod
    def validate_geo(cls, v):
        if v not in VALID_GEOS:
            raise ValueError(f"GEO must be one of: {VALID_GEOS}")
        return v

    @field_validator("offer")
    @classmethod
    def validate_offer(cls, v):
        if not v or len(v.strip()) < 3:
            raise ValueError("Offer description is required")
        return v.strip()


async def _run_generate(content_type: str, req: GenerateRequest, db: AsyncSession):
    try:
        result = await generate_content(
            content_type=content_type,
            geo=req.geo,
            audience_type=req.audience_type,
            offer=req.offer,
            db=db,
            extra=req.extra or "",
        )
        return {"success": True, "result": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("generate_route_error", content_type=content_type, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/newsletter")
async def gen_newsletter(req: GenerateRequest, db: AsyncSession = Depends(get_db)):
    return await _run_generate("newsletter", req, db)


@router.post("/subject-lines")
async def gen_subject_lines(req: GenerateRequest, db: AsyncSession = Depends(get_db)):
    data = await _run_generate("subject_lines", req, db)
    return {"success": True, "subject_lines": data["result"]}


@router.post("/ab-test")
async def gen_ab_test(req: GenerateRequest, db: AsyncSession = Depends(get_db)):
    data = await _run_generate("ab_test", req, db)
    return {"success": True, "ab_test": data["result"]}


@router.post("/ctas")
async def gen_ctas(req: GenerateRequest, db: AsyncSession = Depends(get_db)):
    data = await _run_generate("ctas", req, db)
    return {"success": True, "ctas": data["result"]}


@router.get("/history")
async def get_history(
    content_type: Optional[str] = None,
    geo: Optional[str] = None,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    if limit > 100:
        limit = 100

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
