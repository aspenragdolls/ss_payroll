from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql://localhost/ss_payroll"
    secret_key: str = "dev-secret-change-in-production"
    openrouter_api_key: str = ""
    openrouter_model: str = "anthropic/claude-3.5-sonnet"
    env: str = "development"
    session_cookie_name: str = "ss_payroll_session"
    session_max_age: int = 60 * 60 * 24 * 7  # 7 days


@lru_cache
def get_settings() -> Settings:
    return Settings()
