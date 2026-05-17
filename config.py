from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    anthropic_api_key: str
    composio_api_key: str
    composio_mcp_url: str
    composio_user_id: str = "team"
    database_url: str = "sqlite+aiosqlite:///./mailchimp_ai.db"
    debug: bool = False

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
