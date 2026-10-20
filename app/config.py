from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed settings, read from TOLLGATE_* environment variables or a .env file."""

    model_config = SettingsConfigDict(env_prefix="TOLLGATE_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://tollgate:tollgate@localhost:5432/tollgate"
    redis_url: str = "redis://localhost:6379/0"

    # A return is eligible for this many days after delivery.
    return_window_days: int = 30
    # A stage that fails this many times sends the return to human review.
    stage_max_attempts: int = 3

    # Any OpenAI-compatible provider: Groq, OpenAI, a local vLLM or Ollama. All three values
    # must be set for a provider to be used. The fallback is tried only if the primary fails.
    llm_primary_base_url: str | None = None
    llm_primary_api_key: SecretStr | None = None
    llm_primary_model: str | None = None
    llm_fallback_base_url: str | None = None
    llm_fallback_api_key: SecretStr | None = None
    llm_fallback_model: str | None = None
    llm_timeout_s: float = 30.0
    # Optional per-stage model. Unset means the provider's default model from above.
    llm_intake_model: str | None = None
    prompts_dir: str = "prompts"

@lru_cache
def get_settings() -> Settings:
    return Settings()
