"""Runtime configuration (env-driven, ADR-0005)."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for deployments-service."""

    model_config = SettingsConfigDict(
        env_prefix="", case_sensitive=False, extra="ignore", hide_input_in_errors=True
    )

    api_token: str = Field(
        default="", repr=False, max_length=512, validation_alias="AEGIS_METADATA_API_TOKEN"
    )
    read_token: str = Field(
        default="", repr=False, max_length=512, validation_alias="AEGIS_METADATA_READ_TOKEN"
    )
    dev_mode: bool = Field(default=False, validation_alias="AEGIS_METADATA_DEV_MODE")

    service_name: str = "deployments-service"
    service_port: int = 8701
    environment: str = "dev"
    database_url: str = "sqlite:///./aegis-deployments.db"
    deployment_revision: str = ""
    otel_exporter_otlp_endpoint: str = ""


settings = Settings()
