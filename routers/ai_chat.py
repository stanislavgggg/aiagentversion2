from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, asc
from pydantic import BaseModel
from typing import Optional
import uuid

from services.db import get_db, ChatMessage
from services.ai_service import chat_with_mcp

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    geo: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str


@router.post("", response_model=ChatResponse)
async def send_message(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    session_id = req.session_id or str(uuid.uuid4())

    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(asc(ChatMessage.created_at))
        .limit(20)
    )
    history = result.scalars().all()

    messages = [{"role": m.role, "content": m.content} for m in history]
    messages.append({"role": "user", "content": req.message})

    db.add(ChatMessage(session_id=session_id, role="user", content=req.message))
    await db.commit()

    try:
        reply = await chat_with_mcp(messages=messages, geo=req.geo)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI error: {str(e)}")

    db.add(ChatMessage(session_id=session_id, role="assistant", content=reply))
    await db.commit()

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
            {"role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
            for m in messages
        ],
    }


@router.delete("/{session_id}")
async def clear_session(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session_id)
    )
    for msg in result.scalars().all():
        await db.delete(msg)
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
            "What days of the week show best results?",
            "Suggest an A/B test for next campaign in Lithuania",
            "Which subject line style works better — with emoji or without?",
            "Write 5 subject line options for welcome bonus campaign in Serbia",
        ]
    }
