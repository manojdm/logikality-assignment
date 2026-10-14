"""Runtime configuration loaded from environment variables."""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings. Empty AWS resource names disable remote checks."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        frozen=True,
    )

    app_env: str = "dev"
    aws_region: str = "us-east-1"
    document_bucket: str = ""
    queue_url: str = ""
    idempotency_table: str = ""
    aws_endpoint_url: str | None = None
    kms_key_id: str | None = None
    log_level: str = "INFO"
    app_version: str = "dev"
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1)
    processing_delay_seconds: float = Field(default=0.0, ge=0.0)
    failure_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    visibility_timeout_seconds: int = Field(default=300, ge=1)
    idempotency_ttl_seconds: int = Field(default=7 * 24 * 3600, ge=60)

    @field_validator("aws_endpoint_url", "kms_key_id", mode="before")
    @classmethod
    def empty_str_to_none(cls, value: object) -> object:
        if value == "":
            return None
        return value

    @property
    def aws_configured(self) -> bool:
        return bool(self.document_bucket and self.queue_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
