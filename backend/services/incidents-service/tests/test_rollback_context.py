from datetime import timedelta

from incidents_service.deployment_intelligence import Rollout
from incidents_service.models import Analysis, Incident, Plan, now
from incidents_service.repository import Repository
from incidents_service.rollback_context import context


def test_rollback_requires_linked_bad_rollout_and_unique_known_healthy_target() -> None:
    clock = now()
    repo = Repository("sqlite:///:memory:")
    item = Incident(
        id="incident",
        service="catalog-service",
        environment="dev",
        title="fault",
        status="investigating",
        signals=[],
        evidence_ids=[],
        audit=[],
        analysis=Analysis(summary="unit", confidence="low", evidence_ids=[]),
        plan=Plan(
            action="rollback", target="catalog-service", risk="high", revision="3", reason="unit"
        ),
        change_correlation="deploy-current",
    )
    current = Rollout(
        id="current",
        workload_uid="owned",
        service="catalog-service",
        environment="dev",
        deployment_id="current",
        identity_explicit=True,
        revision="4",
        previous_revision="3",
        started_at=clock - timedelta(seconds=180),
        window_end=clock,
        anchor_source="producer_started_at",
        phase="succeeded",
        last_phase_at=clock - timedelta(seconds=150),
        outcome="bad",
        flagged_at=clock,
        incident_id=item.id,
        source_event_ids=["deploy-current"],
        observation_ids=["metric-anomaly"],
    )
    prior = current.model_copy(
        update={
            "id": "prior",
            "source_event_ids": ["deploy-prior"],
            "deployment_id": "prior",
            "revision": "3",
            "previous_revision": "2",
            "outcome": "healthy",
            "started_at": clock - timedelta(days=1),
            "window_end": clock - timedelta(hours=23),
            "assessed_at": clock - timedelta(hours=22),
        }
    )
    with repo.transaction() as tx:
        tx.save_rollout(current.model_dump(mode="json"))
        tx.save_rollout(prior.model_dump(mode="json"))
        assert context(tx, item, "4", "owned") == {}
        tx.put_state(
            "risk:prior",
            {
                "status": "scored",
                "probability": 0.2,
                "deployment_started_at": prior.started_at.isoformat(),
            },
        )
        result = context(tx, item, "4", "owned")
        assert result["rollout_bad"] and result["deployment_risk"] == 0.2
        assert 180 <= result["deploy_age_seconds"] < 185
        assert context(tx, item, "5", "owned") == {}
        assert context(tx, item, "4", "different-workload") == {}
        current.ambiguous = True
        tx.save_rollout(current.model_dump(mode="json"))
        assert context(tx, item, "4", "owned") == {}
