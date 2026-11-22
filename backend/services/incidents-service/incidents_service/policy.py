"""Policy is the sole authority for execution, independent of RCA wording."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field

from incidents_service.models import Incident, StrictModel


class Rule(StrictModel):
    risk: Literal["low", "medium", "high", "forbidden"]
    requires_approval: bool = True
    reversible: bool = False
    auto: bool = False
    cooldown_seconds: int = Field(default=900, ge=30)


class Policy(StrictModel):
    version: str = "1"
    max_actions_per_hour: int = Field(default=4, ge=1, le=20)
    max_actions_per_incident: int = Field(default=1, ge=1, le=3)
    verification_seconds: int = Field(default=180, ge=30, le=1800)
    recovery_samples: int = Field(default=3, ge=3, le=10)
    rules: dict[str, Rule] = Field(
        default_factory=lambda: {
            "restart": Rule(risk="medium", reversible=True),
            "rollback": Rule(risk="high", reversible=True),
            "scale": Rule(risk="low", reversible=True),
            "replace_instance": Rule(risk="forbidden"),
            "config_update": Rule(risk="forbidden"),
            "escalate": Rule(risk="forbidden"),
        }
    )

    @classmethod
    def load(cls, path: str) -> Policy:
        return cls.model_validate(yaml.safe_load(Path(path).read_text())) if path else cls()


@dataclass(frozen=True)
class PolicyVerdict:
    allowed: bool
    automatic: bool
    reason: str


def evaluate(
    policy: Policy,
    incident: Incident,
    mode: str,
    *,
    actions_in_hour: int,
    incident_actions: int,
    seconds_since_target_action: float,
    target_allowed: bool,
    deploy_age_seconds: float | None = None,
    rollback_distance: int | None = None,
    rollout_bad: bool = False,
    deployment_risk: float | None = None,
    current_replicas: int | None = None,
) -> PolicyVerdict:
    if mode == "observe":
        return PolicyVerdict(False, False, "Kill switch: observe mode blocks all execution")
    rule = policy.rules.get(incident.plan.action)
    if rule is None or rule.risk == "forbidden":
        return PolicyVerdict(False, False, "No executable policy matches this action")
    if not target_allowed:
        return PolicyVerdict(False, False, "Target is outside the configured allowlist")
    if incident.status != "investigating":
        return PolicyVerdict(False, False, "Incident is not awaiting remediation")
    if incident.approval in {"rejected", "deferred"}:
        return PolicyVerdict(False, False, "Operator rejected or deferred this action")
    if (
        actions_in_hour >= policy.max_actions_per_hour
        or incident_actions >= policy.max_actions_per_incident
    ):
        return PolicyVerdict(False, False, "Execution rate limit reached")
    if seconds_since_target_action < rule.cooldown_seconds:
        return PolicyVerdict(False, False, "Target cooldown has not elapsed")
    # Config cannot turn a destructive operation into an automatic low-risk action.
    automatic = (
        mode == "auto-safe"
        and rule.auto
        and rule.risk == "low"
        and rule.reversible
        and not rule.requires_approval
        and incident.plan.action in {"scale", "rollback"}
        and incident.plan.reversible
        and incident.plan.risk == "low"
    )
    if incident.plan.action == "rollback" and automatic:
        # Auto rollback is reserved for a known bad, recent rollout. Other rollback requires approval.
        automatic = (
            incident.change_correlation is not None
            and incident.plan.revision is not None
            and deploy_age_seconds is not None
            and 120 <= deploy_age_seconds <= 1800
            and rollback_distance is not None
            and 1 <= rollback_distance <= 2
            and rollout_bad
            and deployment_risk is not None
            and deployment_risk < 0.8
        )
    if incident.plan.action == "scale" and automatic:
        automatic = (
            current_replicas is not None
            and incident.plan.replicas == current_replicas + 1
            and incident.plan.replicas <= 10
        )
    if not automatic and incident.approval != "approved":
        return PolicyVerdict(False, False, "Explicit operator approval is required")
    return PolicyVerdict(True, automatic, "Versioned policy checks passed")
