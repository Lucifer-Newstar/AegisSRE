"""Validated wire and persistence models. No arbitrary executable actions."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


def now() -> datetime:
    return datetime.now(UTC)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Metric(StrictModel):
    name: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
    labels: dict[str, str] = Field(default_factory=dict, max_length=20)
    value: float
    unit: str = Field(default="", max_length=40)

    @model_validator(mode="after")
    def bounded_labels(self) -> Metric:
        if any(len(k) > 100 or len(v) > 200 for k, v in self.labels.items()):
            raise ValueError("metric label too long")
        return self


class Deployment(StrictModel):
    deployment_id: str | None = Field(
        default=None, min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )
    started_at: AwareDatetime | None = None
    action: Literal["deploy", "rollback", "scale", "restart"]
    revision: str = Field(min_length=1, max_length=200)
    previous_revision: str | None = Field(default=None, max_length=200)
    triggered_by: str = Field(default="operator", max_length=100)
    status: Literal["in_progress", "succeeded", "failed"]
    change_attributes: dict[str, Any] | None = None
    risk_score: float | None = Field(default=None, ge=0, le=1)
    risk_factors: list[str] = Field(default_factory=list, max_length=30)
    canary: dict[str, Any] | None = None
    rollout: dict[str, Any] | None = None


class Log(StrictModel):
    message: str = Field(max_length=4000)
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    attributes: dict[str, Any] = Field(default_factory=dict, max_length=30)


class Event(StrictModel):
    id: str = Field(min_length=1, max_length=160)
    schema_version: Literal["0.2"] = "0.2"
    timestamp: AwareDatetime = Field(default_factory=now)
    source: Literal[
        "prometheus",
        "loki",
        "tempo",
        "k8s",
        "deployment",
        "chaoslab",
        "ml",
        "ai",
        "policy",
        "executor",
        "registry",
    ]
    type: Literal["metric", "log", "deployment", "trace", "k8s_event", "health", "anomaly"]
    service: str = Field(min_length=1, max_length=63, pattern=r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
    environment: str = Field(default="dev", min_length=1, max_length=40)
    severity: Literal["info", "warning", "critical"] = "info"
    correlation_id: str | None = Field(default=None, max_length=160)
    trace_id: str | None = Field(default=None, max_length=64)
    deployment: dict[str, Any] | None = None
    payload: dict[str, Any]

    @model_validator(mode="after")
    def validate_payload(self) -> Event:
        models: dict[str, type[BaseModel]] = {
            "metric": Metric,
            "log": Log,
            "deployment": Deployment,
        }
        if self.type in models:
            models[self.type].model_validate(self.payload)
        if len(self.model_dump_json()) > 16000:
            raise ValueError("event exceeds 16KB")
        if (self.timestamp - now()).total_seconds() > 60:
            raise ValueError("timestamp is more than 60 seconds in the future")
        return self

    def series(self) -> str:
        metric = Metric.model_validate(self.payload)
        key = [
            self.service,
            self.environment,
            metric.name,
            sorted(metric.labels.items()),
            metric.unit,
        ]
        return hashlib.sha256(json.dumps(key).encode()).hexdigest()


class Signal(StrictModel):
    series: str
    metric: str
    labels: dict[str, str]
    unit: str
    event_id: str
    observed: float
    baseline_mean: float
    baseline_std: float
    z_score: float
    isolation_score: float
    model: str = "isolation-forest+z-score-v1"
    recovered_samples: int = 0


class Analysis(StrictModel):
    engine: str = "deterministic-evidence-v1"
    summary: str
    hypotheses: list[dict[str, Any]] = Field(default_factory=list)
    confidence: Literal["low", "medium"]
    evidence_ids: list[str]
    caveat: str = "Correlation is not proof of causation. Operator investigation is required."


class Plan(StrictModel):
    action: Literal["restart", "rollback", "scale", "replace_instance", "config_update", "escalate"]
    target: str
    reason: str
    risk: Literal["low", "medium", "high", "forbidden"]
    requires_approval: bool = True
    executor: Literal["simulation", "kubernetes"] = "simulation"
    revision: str | None = None
    replicas: int | None = Field(default=None, ge=1, le=10)
    policy_version: str = "1"
    reversible: bool = False
    impact: str = ""


class Audit(StrictModel):
    at: datetime = Field(default_factory=now)
    action: str
    actor: str
    detail: str


class Incident(StrictModel):
    id: str
    service: str
    environment: str
    title: str
    severity: Literal["warning", "critical"] = "warning"
    status: Literal["open", "investigating", "remediating", "verifying", "closed", "escalated"] = (
        "open"
    )
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)
    signals: list[Signal]
    evidence_ids: list[str]
    analysis: Analysis
    plan: Plan
    audit: list[Audit]
    approved_by: str | None = None
    approval: Literal["pending", "approved", "rejected", "deferred"] = "pending"
    executed_at: datetime | None = None
    resolved_at: datetime | None = None
    execution_output: str | None = None
    undo: dict[str, Any] | None = None
    change_correlation: str | None = None
    fault_started_at: datetime | None = None
    detected_event_at: datetime | None = None
    verification_deadline: datetime | None = None


class Decision(StrictModel):
    actor: str = Field(min_length=1, max_length=100)
    note: str = Field(default="", max_length=1000)
