"""Configuration, read from environment variables (and an optional .env file)."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Reads the repo-root .env when run from backend/, or a backend/.env. Real environment
    # variables always win over either file (Docker Compose relies on that).
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore")

    # mysql://user:password@host:3306/dbname   or   sqlite:///./dev.db
    database_url: str = "mysql://inventory:inventory@127.0.0.1:3306/inventory"
    api_port: int = 8000
    # Comma-separated list of origins allowed to call the API from a browser.
    cors_origins: str = "http://localhost:5173"
    log_level: str = "INFO"
    # "log" (default) or "webhook"
    alert_notifier: str = "log"
    alert_webhook_url: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
