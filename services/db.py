from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Float, Integer, DateTime, Text, JSON, Index
from datetime import datetime
from typing import Optional, AsyncGenerator

from config import get_settings

settings = get_settings()

# Use asyncpg for Postgres, aiosqlite for SQLite
engine = create_async_engine(
    settings.async_database_url,
    echo=settings.debug,
    pool_size=10 if "postgresql" in settings.async_database_url else 1,
    max_overflow=20 if "postgresql" in settings.async_database_url else 0,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    geo: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class GeneratedContent(Base):
    __tablename__ = "generated_content"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content_type: Mapped[str] = mapped_column(String(50), index=True)
    geo: Mapped[Optional[str]] = mapped_column(String(5), nullable=True, index=True)
    audience_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    language: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    prompt_used: Mapped[str] = mapped_column(Text)
    result: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class VoonixRecord(Base):
    __tablename__ = "voonix_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tracker_id: Mapped[str] = mapped_column(String(200), index=True)
    campaign_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, index=True)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    registrations: Mapped[int] = mapped_column(Integer, default=0)
    ftds: Mapped[int] = mapped_column(Integer, default=0)
    revenue: Mapped[float] = mapped_column(Float, default=0.0)
    period: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    raw_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
