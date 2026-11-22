"""Runtime settings. Dangerous integrations are disabled until configured."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AEGIS_", extra="ignore", hide_input_in_errors=True
    )
    database_url: str = Field(default="sqlite:///./aegis-incidents.db", repr=False)
    api_token: str = Field(default="", repr=False)
    dev_mode: bool = False
    executor: Literal["simulation", "kubernetes"] = "simulation"
    kube_context: str = ""
    kube_namespace: str = Field(
        default="aegissre-demo",
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$",
    )
    kube_evidence_enabled: bool = False
    kube_api_url: str = ""
    kube_token_path: str = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    kube_ca_path: str = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    kube_poll_seconds: int = Field(default=30, ge=15, le=300)
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
    llm_api_key: str = Field(default="", repr=False)
    llm_allow_remote: bool = False
    llm_timeout_seconds: int = Field(default=30, ge=5, le=120)
    llm_max_output_tokens: int = Field(default=1024, ge=128, le=4096)
    llm_requests_per_hour: int = Field(default=10, ge=1, le=100)
    llm_requests_per_day: int = Field(default=50, ge=1, le=1000)
    redis_url: str = Field(default="", repr=False)
    environment: str = Field(
        default="dev", min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$"
    )
    knowledge_enabled: bool = False
    collector_enabled: bool = False
    worker_enabled: bool = False

    @model_validator(mode="after")
    def safe_config(self) -> Settings:
        import re
        from urllib.parse import urlsplit

        if not 1 <= len(self.allowed_targets) <= 20 or len(set(self.allowed_targets)) != len(
            self.allowed_targets
        ):
            raise ValueError("Configure 1..20 distinct allowed service targets")
        if any(
            len(target) > 63 or not re.fullmatch(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?", target)
            for target in self.allowed_targets
        ):
            raise ValueError("Invalid allowed service target")
        for endpoint in (
            self.prometheus_url,
            self.loki_url,
            self.tempo_url,
            self.registry_url,
            self.deployments_url,
        ):
            if endpoint:
                parsed = urlsplit(endpoint)
                if (
                    parsed.scheme not in {"http", "https"}
                    or not parsed.hostname
                    or parsed.username
                    or parsed.password
                    or parsed.query
                    or parsed.fragment
                ):
                    raise ValueError(
                        "Evidence origins must be HTTP(S) URLs without credentials/query/fragment"
                    )
        if self.kube_evidence_enabled:
            parsed = urlsplit(self.kube_api_url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or parsed.path not in {"", "/"}
            ):
                raise ValueError("Kubernetes evidence requires an explicit HTTPS API origin")
            if not self.worker_enabled or not self.kube_token_path or not self.kube_ca_path:
                raise ValueError(
                    "Kubernetes evidence requires delivery worker, projected token and CA paths"
                )
            if self.dev_mode or not self.api_token:
                raise ValueError("Kubernetes evidence requires authenticated non-dev mode")
            if parsed.port is not None and not 1 <= parsed.port <= 65535:
                raise ValueError("Invalid Kubernetes API port")
        if self.worker_enabled and not self.redis_url:
            raise ValueError("The worker requires AEGIS_REDIS_URL")
        if self.collector_enabled and not self.worker_enabled:
            raise ValueError("The collector requires the durable delivery worker")
        if self.collector_enabled and not (
            self.prometheus_url and self.registry_url and self.deployments_url
        ):
            raise ValueError(
                "Collection requires configured Prometheus, registry and deployment origins"
            )
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
        from incidents_service.providers import ProviderConfig

        ProviderConfig(
            provider=self.llm_provider,
            base_url=self.llm_url,
            model=self.llm_model,
            api_key=self.llm_api_key,
            allow_remote=self.llm_allow_remote,
            timeout_seconds=self.llm_timeout_seconds,
            max_output_tokens=self.llm_max_output_tokens,
        )
        return self
