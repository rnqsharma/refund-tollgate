from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed settings, read from TOLLGATE_* environment variables or a .env file."""

    model_config = SettingsConfigDict(env_prefix="TOLLGATE_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://tollgate:tollgate@localhost:5432/tollgate"
    redis_url: str = "redis://localhost:6379/0"


@lru_cache
def get_settings() -> Settings:
    return Settings()
