from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Anthropic
    anthropic_api_key: str

    # Composio — только MCP URL + API key
    composio_api_key: str
    composio_mcp_url: str          # URL из: python -c "from composio import Composio; ..."
    composio_user_id: str = "team"

    # App
    database_url: str = "sqlite+aiosqlite:///./mailchimp_ai.db"
    debug: bool = False

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
