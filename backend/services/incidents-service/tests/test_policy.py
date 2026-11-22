from __future__ import annotations

from typing import Any

from incidents_service.models import Analysis, Incident, Plan
from incidents_service.policy import Policy, Rule, evaluate


def item() -> Incident:
    return Incident(
        id="inc-test",
        service="catalog-service",
        environment="dev",
        title="test",
        status="investigating",
        signals=[],
        evidence_ids=[],
        audit=[],
        analysis=Analysis(summary="test", confidence="low", evidence_ids=[]),
        plan=Plan(
            action="rollback",
            target="catalog-service",
            reason="bad rollout",
            risk="low",
            reversible=True,
            revision="3",
        ),
        change_correlation="deploy-4",
    )


def verdict(policy: Policy, incident: Incident, **kwargs: Any) -> Any:
    defaults: dict[str, Any] = {
        "actions_in_hour": 0,
        "incident_actions": 0,
        "seconds_since_target_action": 10000,
        "target_allowed": True,
    }
    defaults.update(kwargs)
    return evaluate(policy, incident, "auto-safe", **defaults)


def test_auto_rollback_requires_every_safety_condition() -> None:
    policy = Policy(
        rules={"rollback": Rule(risk="low", requires_approval=False, auto=True, reversible=True)}
    )
    incident = item()
    context = {
        "deploy_age_seconds": 180,
        "rollback_distance": 1,
        "rollout_bad": True,
        "deployment_risk": 0.4,
    }
    assert verdict(policy, incident, **context).automatic
    for field, value in [
        ("deploy_age_seconds", 0),
        ("deploy_age_seconds", 4000),
        ("rollback_distance", 3),
        ("rollout_bad", False),
        ("deployment_risk", 0.9),
        ("target_allowed", False),
        ("actions_in_hour", 4),
        ("seconds_since_target_action", 0),
    ]:
        changed = {**context, field: value}
        assert not verdict(policy, incident, **changed).allowed
    assert not verdict(policy, incident).allowed  # missing context cannot authorize execution


def test_high_risk_action_never_auto_executes() -> None:
    policy = Policy(
        rules={"rollback": Rule(risk="high", requires_approval=False, auto=True, reversible=True)}
    )
    incident = item()
    assert not verdict(policy, incident).allowed
    incident.approval, incident.approved_by = "approved", "navin"
    result = verdict(policy, incident)
    assert result.allowed and not result.automatic


def test_forbidden_cannot_be_bypassed_with_approval() -> None:
    incident = item()
    incident.plan.action, incident.approval = "config_update", "approved"
    assert not verdict(Policy(), incident).allowed
