"""Complete observed rollback prerequisites, never inferred risk or revision IDs."""

from __future__ import annotations

from typing import Any

from incidents_service.deployment_intelligence import Rollout
from incidents_service.models import Incident, now
from incidents_service.repository import Transaction


def context(
    tx: Transaction, incident: Incident, live_revision: str, live_uid: str
) -> dict[str, Any]:
    if not incident.change_correlation or not incident.plan.revision:
        return {}
    documents = tx.list_rollouts(
        service=incident.service, environment=incident.environment, limit=501
    )
    if len(documents) > 500:
        return {}
    rows = [Rollout.model_validate(document) for document in documents]
    bad = [row for row in rows if incident.change_correlation in row.source_event_ids]
    if len(bad) != 1:
        return {}
    row = bad[0]
    if (
        row.workload_uid != live_uid
        or not row.identity_explicit
        or row.ambiguous
        or row.outcome != "bad"
        or row.revision != live_revision
        or row.previous_revision != incident.plan.revision
        or row.incident_id != incident.id
        or row.flagged_at is None
        or not row.observation_ids
        or row.anchor_source != "producer_started_at"
    ):
        return {}
    prior = [
        item
        for item in rows
        if item.workload_uid == live_uid
        and item.revision == incident.plan.revision
        and item.identity_explicit
        and not item.ambiguous
        and item.outcome == "healthy"
        and item.assessed_at is not None
        and item.assessed_at < row.started_at
        and item.window_end < row.started_at
    ]
    if len(prior) != 1:
        return {}
    risk = tx.get_state("risk:" + prior[0].id, None)
    if (
        not risk
        or risk.get("status") != "scored"
        or risk.get("probability") is None
        or risk.get("deployment_started_at") != prior[0].started_at.isoformat()
    ):
        return {}
    return {
        "deploy_age_seconds": (now() - row.started_at).total_seconds(),
        "rollout_bad": True,
        "deployment_risk": risk["probability"],
    }
