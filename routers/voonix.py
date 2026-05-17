from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
import csv
import json
import io

from services.db import get_db, VoonixRecord

router = APIRouter()


class TrackerMapping(BaseModel):
    tracker_id: str
    campaign_id: str


class TrackerMappingBatch(BaseModel):
    mappings: list[TrackerMapping]


@router.post("/import/csv")
async def import_csv(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    imported = 0
    errors = []

    for i, row in enumerate(reader):
        tracker_id = row.get("tracker_id") or row.get("tracker") or row.get("Tracker ID")
        if not tracker_id:
            errors.append(f"Row {i+2}: missing tracker_id")
            continue
        try:
            record = VoonixRecord(
                tracker_id=str(tracker_id).strip(),
                clicks=int(str(row.get("clicks", 0)).replace(",", "") or 0),
                registrations=int(str(row.get("registrations", row.get("regs", 0))).replace(",", "") or 0),
                ftds=int(str(row.get("ftds", 0)).replace(",", "") or 0),
                revenue=float(str(row.get("revenue", 0)).replace(",", "").replace("€", "") or 0),
                period=row.get("period", None),
                raw_data=dict(row),
            )
            db.add(record)
            imported += 1
        except Exception as e:
            errors.append(f"Row {i+2}: {str(e)}")

    await db.commit()
    return {"imported": imported, "errors": errors[:10]}


@router.post("/import/json")
async def import_json(data: list[dict], db: AsyncSession = Depends(get_db)):
    imported = 0
    for row in data:
        tracker_id = row.get("tracker_id") or row.get("tracker")
        if not tracker_id:
            continue
        record = VoonixRecord(
            tracker_id=str(tracker_id),
            clicks=int(row.get("clicks", 0)),
            registrations=int(row.get("registrations", row.get("regs", 0))),
            ftds=int(row.get("ftds", 0)),
            revenue=float(row.get("revenue", 0)),
            period=row.get("period", None),
            raw_data=row,
        )
        db.add(record)
        imported += 1
    await db.commit()
    return {"imported": imported}


@router.post("/map-trackers")
async def map_trackers(batch: TrackerMappingBatch, db: AsyncSession = Depends(get_db)):
    mapped = 0
    for mapping in batch.mappings:
        result = await db.execute(
            select(VoonixRecord).where(VoonixRecord.tracker_id == mapping.tracker_id)
        )
        for record in result.scalars().all():
            record.campaign_id = mapping.campaign_id
            mapped += 1
    await db.commit()
    return {"mapped_records": mapped}


@router.get("/status")
async def voonix_status(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(VoonixRecord))
    all_records = result.scalars().all()
    mapped = [r for r in all_records if r.campaign_id]
    return {
        "total_records": len(all_records),
        "mapped": len(mapped),
        "unmapped": len(all_records) - len(mapped),
        "total_ftds": sum(r.ftds for r in all_records),
        "total_revenue": sum(r.revenue for r in all_records),
    }


@router.get("/unmapped")
async def get_unmapped(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(VoonixRecord).where(VoonixRecord.campaign_id.is_(None))
    )
    trackers = list({r.tracker_id for r in result.scalars().all()})
    return {"unmapped_trackers": trackers, "count": len(trackers)}
