from datetime import timedelta
from typing import Any

import pytest
from incidents_service.change_risk import Attributes, key, predict, preview, state
from incidents_service.deployment_intelligence import Rollout, register
from incidents_service.models import Event, now
from incidents_service.repository import Repository


def attrs(size: int = 10) -> Attributes:
    return Attributes(
        changed_lines=size,
        affected_services=1,
        owner_prior_deployments=5,
        source_reference="unit-fixture:not-independent-evidence",
    )


def test_preview_missing_health_stays_unknown_and_identity_is_frozen() -> None:
    repo = Repository("sqlite:///:memory:")
    with repo.transaction() as tx:
        result = preview(tx, "catalog-service", "dev", "release", "v2", attrs())
        assert result["probability"] is None
        assert result == preview(tx, "catalog-service", "dev", "release", "v2", attrs())
        with pytest.raises(ValueError):
            preview(tx, "catalog-service", "dev", "release", "different", attrs())
        with pytest.raises(ValueError):
            preview(tx, "catalog-service", "dev", "release", "v2", attrs(100))
        start = now()
        register(
            tx,
            Event(
                id="deploy",
                type="deployment",
                source="deployment",
                service="catalog-service",
                timestamp=start,
                payload={
                    "action": "deploy",
                    "status": "in_progress",
                    "revision": "v2",
                    "deployment_id": "release",
                    "started_at": start.isoformat(),
                },
            ),
        )
        assert (
            tx.get_state("change-risk:" + key("catalog-service", "dev", "release"), None) == result
        )
        assert result["is_predeploy_prediction"] and not result["authorizes_execution"]


def test_actual_chronological_inputs_fit_and_later_unknown_cross_scope_do_not_train() -> None:
    repo = Repository("sqlite:///:memory:")
    clock = now()
    health: dict[str, Any] = {
        "errors_ok": True,
        "latency_ok": True,
        "slo_ok": True,
        "evidence_id": "unit-health",
        "timestamp": clock.isoformat(),
    }
    with repo.transaction() as tx:
        for index in range(25):
            identity = "prior-" + str(index)
            start = clock - timedelta(days=2, minutes=index * 5)
            row = Rollout(
                id=identity,
                service="catalog-service",
                environment="dev",
                deployment_id=identity,
                identity_explicit=True,
                revision=identity,
                previous_revision=None,
                started_at=start,
                window_end=start + timedelta(seconds=180),
                anchor_source="producer_started_at",
                phase="succeeded",
                last_phase_at=start,
                outcome="bad" if index < 10 else "healthy",
                assessed_at=clock - timedelta(days=1),
            )
            if index == 20:
                row.assessed_at = clock + timedelta(seconds=1)
            elif index == 21:
                row.ambiguous = True
            elif index == 22:
                row.environment = "prod"
            elif index == 23:
                row.service = "cart-service"
            elif index == 24:
                row.outcome = "insufficient"
            tx.save_rollout(row.model_dump(mode="json"))
            tx.put_state(
                "change-risk:" + identity,
                {
                    "is_predeploy_prediction": True,
                    "at": start.isoformat(),
                    "attributes": attrs(1000 if index < 10 else 10).model_dump(),
                    "health": health,
                },
            )
        result = predict(tx, "catalog-service", "dev", clock, attrs(500), health)
        assert result["status"] == "scored" and result["confirmed_outcomes"] == 20
        assert 0 <= result["probability"] <= 1
        assert len(result["training_records"]) == 20
        assert (
            result["training_digest"]
            == predict(tx, "catalog-service", "dev", clock, attrs(500), health)["training_digest"]
        )
        assert not result["authorizes_execution"]
        assert predict(tx, "catalog-service", "dev", clock, None, health)["probability"] is None
        assert predict(tx, "catalog-service", "dev", clock, attrs(), None)["probability"] is None


def test_stale_or_incomplete_health_is_not_a_feature() -> None:
    repo = Repository("sqlite:///:memory:")
    at = now()
    with repo.transaction() as tx:
        tx.add_event(
            Event(
                id="old-health",
                type="health",
                source="registry",
                service="catalog-service",
                timestamp=at - timedelta(seconds=61),
                payload={"errors_ok": True, "latency_ok": True, "slo_ok": True},
            )
        )
        assert state(tx, "catalog-service", "dev", at) is None
        tx.add_event(
            Event(
                id="new-health",
                type="health",
                source="registry",
                service="catalog-service",
                timestamp=at,
                payload={"errors_ok": True, "latency_ok": True},
            )
        )
        assert state(tx, "catalog-service", "dev", at) is None
