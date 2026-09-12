"""Application configuration using pydantic-settings."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    llm_provider: str = Field(default="fake", description="gemini | fake")
    llm_model: str = Field(default="gemini-3.1-flash-lite")
    gemini_api_key: str = Field(default="")

    # Database
    database_url: str = Field(default="sqlite:///./data/fkl.sqlite3")

    # Storage
    upload_dir: Path = Field(default=Path("./data/uploads"))
    render_dir: Path = Field(default=Path("./data/renders"))
    max_upload_mb: int = Field(default=50)

    # App
    pipeline_version: str = Field(default="1.0.0")
    log_level: str = Field(default="INFO")
    max_metric_llm_calls_per_run: int = Field(default=450)

    @model_validator(mode="after")
    def check_llm_credentials(self) -> "Settings":
        if self.llm_provider == "gemini" and not self.gemini_api_key:
            raise ValueError(
                "GEMINI_API_KEY must be set when LLM_PROVIDER=gemini.\n"
                "Copy .env.example to .env and fill in the key, or set LLM_PROVIDER=fake for testing."
            )
        return self

    def ensure_dirs(self) -> None:
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.render_dir.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.ensure_dirs()
    return _settings
