from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Float, Integer, DateTime, Text, JSON
from datetime import datetime
from typing import Optional, AsyncGenerator

from config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, echo=settings.debug)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class GeneratedContent(Base):
    __tablename__ = "generated_content"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content_type: Mapped[str] = mapped_column(String)
    geo: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    audience_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    language: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    prompt_used: Mapped[str] = mapped_column(Text)
    result: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class VoonixRecord(Base):
    __tablename__ = "voonix_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tracker_id: Mapped[str] = mapped_column(String)
    campaign_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    registrations: Mapped[int] = mapped_column(Integer, default=0)
    ftds: Mapped[int] = mapped_column(Integer, default=0)
    revenue: Mapped[float] = mapped_column(Float, default=0.0)
    period: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    raw_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
