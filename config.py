from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional


class Settings(BaseSettings):
    # Anthropic
    anthropic_api_key: str

    # Composio MCP
    composio_api_key: str
    composio_mcp_url: str
    composio_user_id: str = "team"

    # Database — Railway Postgres or SQLite fallback
    database_url: str = "sqlite+aiosqlite:///./mailchimp_ai.db"

    # App
    debug: bool = False
    environment: str = "production"

    # Rate limiting
    rate_limit_per_minute: int = 20

    @property
    def async_database_url(self) -> str:
        """Convert postgres:// to postgresql+asyncpg:// for SQLAlchemy async."""
        url = self.database_url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://") and "asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
