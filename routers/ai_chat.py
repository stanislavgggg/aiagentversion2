"""
AI Chat router with streaming.
POST /api/chat          → streaming SSE response
POST /api/chat/sync     → non-streaming (fallback)
GET  /api/chat/history/{session_id}
DELETE /api/chat/{session_id}
GET  /api/chat/examples
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, asc, delete
from pydantic import BaseModel
from typing import Optional
import uuid
import json

from services.db import get_db, ChatMessage
from services.ai_service import chat_with_mcp
from services.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    geo: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str


async def _load_history(session_id: str, db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(asc(ChatMessage.created_at))
        .limit(20)
    )
    return [{"role": m.role, "content": m.content} for m in result.scalars().all()]


async def _save_message(session_id: str, role: str, content: str, geo: Optional[str], db: AsyncSession):
    db.add(ChatMessage(session_id=session_id, role=role, content=content, geo=geo))
    await db.commit()


@router.post("/stream")
async def stream_chat(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    """
    Streaming endpoint — returns Server-Sent Events.
    Frontend reads chunks as they arrive (no waiting for full response).
    """
    session_id = req.session_id or str(uuid.uuid4())

    history = await _load_history(session_id, db)
    messages = history + [{"role": "user", "content": req.message}]

    await _save_message(session_id, "user", req.message, req.geo, db)

    # Collect full reply for saving to DB
    full_reply = []

    async def event_generator():
        # First send session_id so frontend knows it
        yield f"data: {json.dumps({'session_id': session_id})}\n\n"

        async for chunk in chat_stream(messages=messages, geo=req.geo):
            # Parse chunk to collect full reply
            try:
                data = json.loads(chunk.replace("data: ", "").strip())
                if "text" in data:
                    full_reply.append(data["text"])
            except Exception:
                pass
            yield chunk

        # Save complete reply to DB
        if full_reply:
            complete = "".join(full_reply)
            await _save_message(session_id, "assistant", complete, req.geo, db)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("", response_model=ChatResponse)
async def chat_sync(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    """Non-streaming fallback — returns full response at once."""
    session_id = req.session_id or str(uuid.uuid4())

    history = await _load_history(session_id, db)
    messages = history + [{"role": "user", "content": req.message}]

    await _save_message(session_id, "user", req.message, req.geo, db)

    try:
        reply = await chat_with_mcp(messages=messages, geo=req.geo)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    await _save_message(session_id, "assistant", reply, req.geo, db)
    return ChatResponse(reply=reply, session_id=session_id)


@router.get("/history/{session_id}")
async def get_history(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(asc(ChatMessage.created_at))
    )
    messages = result.scalars().all()
    return {
        "session_id": session_id,
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ],
    }


@router.delete("/{session_id}")
async def clear_session(session_id: str, db: AsyncSession = Depends(get_db)):
    await db.execute(delete(ChatMessage).where(ChatMessage.session_id == session_id))
    await db.commit()
    return {"message": f"Session {session_id} cleared."}


@router.get("/examples")
async def example_questions():
    return {
        "examples": [
            "Show all 2024 campaigns with open rate above 35%",
            "What worked best in Spain for casino audience?",
            "Best subject lines by open rate in Latvia",
            "Write a new email for Sportsbook audience in Croatia",
            "Compare Casino vs Sportsbook results across all GEOs",
            "Generate 3 new newsletter angles based on top campaigns",
            "What days of the week show the best results?",
            "Suggest an A/B test for the next campaign in Lithuania",
            "Which subject line style works better — with emoji or without?",
            "Write 5 subject line options for a welcome bonus campaign in Serbia",
        ]
    }
