"""Chronological change-attribute logistic baseline, never an execution grant."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

from pydantic import Field
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
from sklearn.pipeline import make_pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

from incidents_service.deployment_intelligence import Rollout
from incidents_service.models import StrictModel
from incidents_service.repository import Transaction


class Attributes(StrictModel):
    changed_lines: int = Field(ge=0, le=1000000)
    affected_services: int = Field(ge=1, le=1000)
    owner_prior_deployments: int = Field(ge=0, le=100000)
    # Provenance is recorded as a caller assertion, not silently authenticated.
    source_reference: str = Field(min_length=1, max_length=500)


def state(tx: Transaction, service: str, environment: str, at: datetime) -> dict[str, Any] | None:
    events = tx.recent_events(
        service, environment, "health", 1, not_after=at, not_before=at - timedelta(seconds=60)
    )
    if not events:
        return None
    event = events[0]
    payload = event["payload"]
    if any(not isinstance(payload.get(k), bool) for k in ("errors_ok", "latency_ok", "slo_ok")):
        return None
    return {
        "evidence_id": event["id"],
        "timestamp": event["timestamp"],
        "errors_ok": payload["errors_ok"],
        "latency_ok": payload["latency_ok"],
        "slo_ok": payload["slo_ok"],
    }


def vector(attributes: Attributes, health: dict[str, Any], at: datetime) -> list[float]:
    import math

    hour = at.hour + at.minute / 60
    return [
        math.log1p(attributes.changed_lines),
        float(attributes.affected_services),
        math.log1p(attributes.owner_prior_deployments),
        math.sin(hour * math.tau / 24),
        math.cos(hour * math.tau / 24),
        float(not health["errors_ok"]),
        float(not health["latency_ok"]),
        float(not health["slo_ok"]),
    ]


def predict(
    tx: Transaction,
    service: str,
    environment: str,
    at: datetime,
    attributes: Attributes | None,
    health: dict[str, Any] | None,
) -> dict[str, Any]:
    documents = tx.list_rollouts(service=service, environment=environment, limit=501)
    training = []
    for document in documents:
        row = Rollout.model_validate(document)
        snapshot = tx.get_state("change-risk:" + row.id, None)
        if (
            row.identity_explicit
            and not row.ambiguous
            and row.outcome in {"bad", "healthy"}
            and row.assessed_at is not None
            and row.assessed_at < at
            and row.window_end < at
            and row.last_phase_at < at
            and (row.flagged_at is None or row.flagged_at < at)
            and snapshot
            and snapshot.get("is_predeploy_prediction")
            and snapshot.get("attributes")
            and snapshot.get("health")
        ):
            training.append(
                {
                    "id": row.id,
                    "outcome": row.outcome,
                    "features": vector(
                        Attributes.model_validate(snapshot["attributes"]),
                        snapshot["health"],
                        datetime.fromisoformat(snapshot["at"]),
                    ),
                    "source_event_ids": row.source_event_ids,
                    "observation_ids": row.observation_ids,
                }
            )
    training.sort(key=lambda x: str(x["id"]))
    digest = hashlib.sha256(json.dumps(training, sort_keys=True).encode()).hexdigest()
    bad = sum(item["outcome"] == "bad" for item in training)
    sufficient = (
        len(training) >= 20
        and bad >= 5
        and len(training) - bad >= 5
        and len(documents) <= 500
        and attributes is not None
        and health is not None
    )
    probability: float | None = None
    if sufficient:
        assert attributes is not None and health is not None
        model = make_pipeline(
            StandardScaler(), LogisticRegression(C=1, random_state=42, max_iter=1000)
        )
        model.fit(
            [item["features"] for item in training],
            [int(item["outcome"] == "bad") for item in training],
        )
        probability = float(model.predict_proba([vector(attributes, health, at)])[0][1])
    return {
        "model_version": "change-logistic-v1",
        "probability": probability,
        "status": "scored" if sufficient else "insufficient_evidence",
        "classification": "higher"
        if probability is not None and probability >= 0.5
        else "lower"
        if sufficient
        else "unknown",
        "attributes": attributes.model_dump() if attributes else None,
        "health": health,
        "at": at.isoformat(),
        "confirmed_outcomes": len(training),
        "bad_outcomes": bad,
        "training_digest": digest,
        "training_records": training,
        "authorizes_execution": False,
        "caveat": "Fixed regularized logistic baseline from prior pre-deploy snapshots and later confirmed outcomes. Caller-supplied change/owner attributes are not independently verified. Missing features, stale health, sparse classes or truncated history stay unknown. No held-out recall or causal validity measured. No execution authority.",
    }


def key(service: str, environment: str, identity: str) -> str:
    return (
        "dep_"
        + hashlib.sha256(
            (service + "\0" + environment + "\0logical:" + identity).encode()
        ).hexdigest()
    )


def preview(
    tx: Transaction,
    service: str,
    environment: str,
    identity: str,
    revision: str,
    attributes: Attributes,
) -> dict[str, Any]:
    from incidents_service.models import now

    token = key(service, environment, identity)
    existing = tx.get_state("change-preview:" + token, None)
    if existing is not None:
        if existing["revision"] != revision or existing["attributes"] != attributes.model_dump():
            raise ValueError("Preview identity conflict")
        return dict(existing)
    if tx.rollout(token) is not None:
        raise ValueError("Deployment has already been registered")
    at = now()
    result = predict(tx, service, environment, at, attributes, state(tx, service, environment, at))
    result.update(
        {
            "revision": revision,
            "deployment_id": identity,
            "computed_at": at.isoformat(),
            "is_predeploy_prediction": True,
            "timing": "predeploy_preview",
        }
    )
    tx.put_state("change-preview:" + token, result)
    return result


def bind(tx: Transaction, row: Rollout, attributes: dict[str, Any] | None) -> None:
    from incidents_service.models import now

    if tx.get_state("change-risk:" + row.id, None) is not None:
        return
    before = tx.get_state("change-preview:" + row.id, None)
    if (
        before
        and before["revision"] == row.revision
        and 0
        <= (row.started_at - datetime.fromisoformat(before["computed_at"])).total_seconds()
        <= 60
    ):
        if (
            attributes is not None
            and Attributes.model_validate(attributes).model_dump() != before["attributes"]
        ):
            raise ValueError("Deployment attributes differ from frozen preview")
        result = dict(before)
    else:
        at = now()
        result = predict(
            tx,
            row.service,
            row.environment,
            row.started_at,
            Attributes.model_validate(attributes) if attributes else None,
            state(tx, row.service, row.environment, row.started_at),
        )
        result.update(
            {
                "revision": row.revision,
                "computed_at": at.isoformat(),
                "is_predeploy_prediction": False,
                "timing": "postdeploy_registration",
            }
        )
    tx.put_state("change-risk:" + row.id, result)
