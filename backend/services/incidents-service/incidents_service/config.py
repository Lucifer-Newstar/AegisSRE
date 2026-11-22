"""Runtime settings. Dangerous integrations are disabled until configured."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AEGIS_", extra="ignore")
    database_url: str = "sqlite:///./aegis-incidents.db"
    api_token: str = ""
    dev_mode: bool = False
    executor: Literal["simulation", "kubernetes"] = "simulation"
    kube_context: str = ""
    kube_namespace: str = "aegissre-demo"
    allowed_targets: list[str] = Field(
        default_factory=lambda: [
            "catalog-service",
            "cart-service",
            "order-service",
            "payment-service",
        ]
    )
    policy_path: str = ""
    poll_seconds: int = Field(default=15, ge=5, le=300)
    prometheus_url: str = ""
    loki_url: str = ""
    tempo_url: str = ""
    registry_url: str = ""
    deployments_url: str = ""
    llm_provider: Literal["disabled", "ollama", "openai"] = "disabled"
    llm_url: str = "http://localhost:11434"
    llm_model: str = ""
    llm_api_key: str = ""
    worker_enabled: bool = False

    @model_validator(mode="after")
    def safe_config(self) -> Settings:
        if not self.api_token and not self.dev_mode:
            raise ValueError(
                "Set AEGIS_API_TOKEN, or explicitly enable AEGIS_DEV_MODE for local simulation"
            )
        if self.executor == "kubernetes" and (
            self.dev_mode or not self.api_token or not self.kube_context
        ):
            raise ValueError(
                "Kubernetes execution requires a token, an explicit context and dev mode off"
            )
        if self.llm_provider != "disabled" and not self.llm_model:
            raise ValueError("An explicit LLM model is required")
        return self
