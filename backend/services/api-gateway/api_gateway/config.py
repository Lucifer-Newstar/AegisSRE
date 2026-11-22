from __future__ import annotations

from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AEGIS_GATEWAY_", extra="ignore", hide_input_in_errors=True
    )
    api_token: str = Field(default="", repr=False, max_length=512)
    incidents_token: str = Field(default="", repr=False, max_length=512)
    redis_url: str = Field(default="redis://127.0.0.1:6379/0", repr=False)
    registry_url: str = "http://127.0.0.1:8101"
    deployments_url: str = "http://127.0.0.1:8701"
    incidents_url: str = "http://127.0.0.1:8201"
    requests_per_minute: int = Field(default=120, ge=1, le=10000)
    failed_auth_per_minute: int = Field(default=30, ge=1, le=1000)
    operator: str = Field(default="token:operator", min_length=1, max_length=100)

    @model_validator(mode="after")
    def bounded_configuration(self) -> Settings:
        if not self.api_token or not self.incidents_token:
            raise ValueError("Gateway and incidents bearer tokens must be explicitly configured")
        for endpoint in (self.registry_url, self.deployments_url, self.incidents_url):
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
                    "Upstream origins must be fixed HTTP(S) URLs without credentials/query/fragment"
                )
        return self
