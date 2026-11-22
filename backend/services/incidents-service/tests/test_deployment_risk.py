from __future__ import annotations

from datetime import timedelta
from typing import Any

from incidents_service.deployment_intelligence import Rollout, register
from incidents_service.deployment_risk import score, scores
from incidents_service.models import Event, now
from incidents_service.repository import Repository


def row(key: str, **overrides: Any) -> Rollout:
    start = now() - timedelta(days=2)
    body = dict(
        id=key,
        service="catalog-service",
        environment="dev",
        deployment_id=key,
        identity_explicit=True,
        revision=key,
        previous_revision=None,
        started_at=start,
        window_end=start + timedelta(minutes=3),
        anchor_source="producer_started_at",
        phase="succeeded",
        last_phase_at=start,
        outcome="healthy",
        assessed_at=start + timedelta(minutes=4),
    )
    body.update(overrides)
    return Rollout.model_validate(body)


def test_no_training_data_means_unknown_not_safe() -> None:
    repo = Repository("sqlite:///:memory:")
    with repo.transaction() as tx:
        result = score(tx, row("current", started_at=now()))
    assert result["probability"] is None and result["classification"] == "unknown"
    assert not result["authorizes_execution"]


def test_empirical_model_records_real_prior_labels_and_digest() -> None:
    repo = Repository("sqlite:///:memory:")
    with repo.transaction() as tx:
        for index in range(10):
            tx.save_rollout(
                row(str(index), outcome="bad" if index < 7 else "healthy").model_dump(mode="json")
            )
        current = row("current", started_at=now())
        result = score(tx, current)
        assert result["probability"] == 8 / 12
        assert result["classification"] == "high"
        assert len(result["training_records"]) == 10
        assert result["training_digest"] == score(tx, current)["training_digest"]


def test_future_assessment_ambiguity_unknown_and_cross_scope_do_not_train() -> None:
    repo = Repository("sqlite:///:memory:")
    with repo.transaction() as tx:
        cases: list[tuple[str, dict[str, Any]]] = [
            ("future", {"assessed_at": now() + timedelta(seconds=2)}),
            ("unknown", {"outcome": "insufficient"}),
            ("ambiguous", {"ambiguous": True}),
            ("other-service", {"service": "cart-service"}),
            ("other-env", {"environment": "prod"}),
            ("legacy", {"assessed_at": None}),
        ]
        for key, values in cases:
            tx.save_rollout(row(key, **values).model_dump(mode="json"))
        result = score(tx, row("current", started_at=now()))
        assert result["confirmed_outcomes"] == 0


def test_registration_freezes_score_and_api_does_not_retrain_from_future() -> None:
    repo = Repository("sqlite:///:memory:")
    start = now() - timedelta(seconds=5)
    event = Event(
        id="deployment-one",
        service="catalog-service",
        type="deployment",
        source="deployment",
        timestamp=start,
        payload={
            "action": "deploy",
            "revision": "new",
            "status": "in_progress",
            "deployment_id": "logical-one",
            "started_at": start.isoformat(),
        },
    )
    with repo.transaction() as tx:
        register(tx, event)
        initial = scores(tx, "catalog-service", "dev", now(), 10)
        assert initial["items"][0]["prediction"]["probability"] is None
        for index in range(10):
            tx.save_rollout(row(str(index), outcome="bad").model_dump(mode="json"))
        actual = next(
            item
            for item in scores(tx, "catalog-service", "dev", now(), 50)["items"]
            if item["revision"] == "new"
        )
        assert actual == initial["items"][0]
        assert actual["prediction"]["is_predeploy_prediction"] is False
