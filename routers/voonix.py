from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
import csv
import json
import io

from services.db import get_db, VoonixRecord
from services.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)


class TrackerMapping(BaseModel):
    tracker_id: str
    campaign_id: str
    notes: Optional[str] = None


class TrackerMappingBatch(BaseModel):
    mappings: list[TrackerMapping]


def _parse_num(val, typ=int):
    try:
        return typ(str(val).replace(",", "").replace("€", "").replace(" ", "") or 0)
    except Exception:
        return 0


@router.post("/import/csv")
async def import_csv(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    if not file.filename.endswith(".csv"):
        raise HTTPException(400, "File must be a CSV")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10MB limit
        raise HTTPException(400, "File too large (max 10MB)")

    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    imported = 0
    errors = []

    for i, row in enumerate(reader):
        tracker_id = (
            row.get("tracker_id") or row.get("tracker") or
            row.get("Tracker ID") or row.get("Tracker")
        )
        if not tracker_id:
            errors.append(f"Row {i+2}: missing tracker_id")
            continue
        try:
            record = VoonixRecord(
                tracker_id=str(tracker_id).strip(),
                clicks=_parse_num(row.get("clicks", 0)),
                registrations=_parse_num(row.get("registrations", row.get("regs", 0))),
                ftds=_parse_num(row.get("ftds", row.get("first_deposits", 0))),
                revenue=_parse_num(row.get("revenue", row.get("net_revenue", 0)), float),
                period=row.get("period", row.get("month", None)),
                raw_data=dict(row),
            )
            db.add(record)
            imported += 1
        except Exception as e:
            errors.append(f"Row {i+2}: {str(e)}")

    await db.commit()
    logger.info("voonix_csv_import", imported=imported, errors=len(errors))
    return {
        "imported": imported,
        "errors": errors[:10],
        "message": f"Imported {imported} records. Use /map-trackers to link them to campaigns.",
    }


@router.post("/import/json")
async def import_json(data: list[dict], db: AsyncSession = Depends(get_db)):
    if len(data) > 10000:
        raise HTTPException(400, "Too many records (max 10,000 per import)")

    imported = 0
    for row in data:
        tracker_id = row.get("tracker_id") or row.get("tracker")
        if not tracker_id:
            continue
        record = VoonixRecord(
            tracker_id=str(tracker_id),
            clicks=_parse_num(row.get("clicks", 0)),
            registrations=_parse_num(row.get("registrations", row.get("regs", 0))),
            ftds=_parse_num(row.get("ftds", 0)),
            revenue=_parse_num(row.get("revenue", 0), float),
            period=row.get("period", None),
            raw_data=row,
        )
        db.add(record)
        imported += 1

    await db.commit()
    logger.info("voonix_json_import", imported=imported)
    return {"imported": imported}


@router.post("/map-trackers")
async def map_trackers(batch: TrackerMappingBatch, db: AsyncSession = Depends(get_db)):
    if len(batch.mappings) > 1000:
        raise HTTPException(400, "Too many mappings (max 1,000 per request)")

    mapped_records = 0
    not_found = []

    for mapping in batch.mappings:
        result = await db.execute(
            select(VoonixRecord).where(VoonixRecord.tracker_id == mapping.tracker_id)
        )
        records = result.scalars().all()
        if not records:
            not_found.append(mapping.tracker_id)
            continue
        for record in records:
            record.campaign_id = mapping.campaign_id
            mapped_records += 1

    await db.commit()
    logger.info("voonix_map_trackers", mapped=mapped_records, not_found=len(not_found))

    return {
        "mapped_records": mapped_records,
        "not_found_trackers": not_found[:20],
        "message": f"Mapped {mapped_records} records. AI now has conversion context.",
    }


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
        "total_revenue": round(sum(r.revenue for r in all_records), 2),
    }


@router.get("/unmapped")
async def get_unmapped(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(VoonixRecord).where(VoonixRecord.campaign_id.is_(None))
    )
    trackers = list({r.tracker_id for r in result.scalars().all()})
    return {
        "unmapped_trackers": sorted(trackers),
        "count": len(trackers),
        "hint": "Share this list with Karina to get the Mailchimp campaign mapping.",
    }
