"""Runtime configuration (env-driven, ADR-0005)."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for registry-service."""

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

    service_name: str = "registry-service"
    service_port: int = 8101
    environment: str = "dev"
    otel_exporter_otlp_endpoint: str = ""
    registry_probe: bool = False
    database_url: str = "sqlite:///./aegis-registry.db"
    registry_allowed_hosts: list[str] = Field(
        default_factory=lambda: [
            "catalog-service",
            "cart-service",
            "order-service",
            "payment-service",
            "registry-service",
            "deployments-service",
            "incidents-service",
            "ml-service",
            "ai-service",
            "evidence-service",
            "policy-service",
            "remediation-service",
            "audit-service",
            "autonomy-service",
        ]
    )


settings = Settings()
