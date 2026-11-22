"""Thin empirical-Bayes deployment risk model over prior observed outcomes.

No invented training data, inferred feature values, random split or current/future
outcome leakage. This estimates a service's historical failure propensity, not
change-specific causal risk. It cannot authorize automatic rollback.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from incidents_service.deployment_intelligence import Rollout
from incidents_service.models import now
from incidents_service.repository import Transaction

MODEL_VERSION = "service-beta-binomial-v1"
MIN_OUTCOMES = 10


def score(tx: Transaction, deployment: Rollout) -> dict[str, Any]:
    # Query an extra row so a bounded training view cannot pretend it is complete.
    documents = tx.list_rollouts(
        service=deployment.service, environment=deployment.environment, limit=501
    )
    rows = [Rollout.model_validate(row) for row in documents]
    eligible = [
        row
        for row in rows
        if row.id != deployment.id
        and row.identity_explicit
        and not row.ambiguous
        and row.window_end < deployment.started_at
        and row.last_phase_at < deployment.started_at
        and row.outcome in {"bad", "healthy"}
        and row.assessed_at is not None
        and row.assessed_at < deployment.started_at
        # A later re-evaluation cannot leak a later bad flag into a pre-deploy model.
        and (row.flagged_at is None or row.flagged_at < deployment.started_at)
    ]
    records = sorted(
        [
            {
                "id": row.id,
                "outcome": row.outcome,
                "source_event_ids": row.source_event_ids,
                "observation_ids": row.observation_ids,
            }
            for row in eligible
        ],
        key=lambda x: str(x["id"]),
    )
    digest = hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()
    failed = sum(row.outcome == "bad" for row in eligible)
    n = len(eligible)
    missing = len(rows) - n - int(any(row.id == deployment.id for row in rows))
    truncated = len(documents) > 500
    sufficient = n >= MIN_OUTCOMES and not truncated
    # Beta(1,1) regularization is fixed before evaluation, never selected for recall.
    probability = (failed + 1) / (n + 2) if sufficient else None
    clock = now()
    return {
        "deployment_id": deployment.id,
        "revision": deployment.revision,
        "service": deployment.service,
        "environment": deployment.environment,
        "deployment_started_at": deployment.started_at.isoformat(),
        "timing": "pre_or_at_deploy"
        if clock <= deployment.started_at
        else "post_deploy_registration",
        "is_predeploy_prediction": clock <= deployment.started_at,
        "computed_at": clock.isoformat(),
        "model_version": MODEL_VERSION,
        "training_digest": digest,
        "training_records": records,
        "prior": {"alpha": 1, "beta": 1},
        "observed_bad": failed,
        "confirmed_outcomes": n,
        "excluded_rows": missing,
        "truncated": truncated,
        "minimum_outcomes": MIN_OUTCOMES,
        "probability": probability,
        "status": "scored" if sufficient else "insufficient_history",
        "classification": "high"
        if probability is not None and probability >= 0.5
        else "lower"
        if sufficient
        else "unknown",
        "authorizes_execution": False,
        "caveat": "Empirical service-level failure propensity, not change-specific risk or validated recall. Unknown outcomes excluded, never healthy. Later observations cannot train a pre-deploy score. No automatic action authority.",
    }


def scores(
    tx: Transaction, service: str, environment: str, at: datetime, limit: int
) -> dict[str, Any]:
    documents = tx.list_rollouts(service=service, environment=environment, limit=limit + 1)
    items = []
    for document in documents[:limit]:
        row = Rollout.model_validate(document)
        if row.started_at > at:
            continue
        snapshot = tx.get_state("risk:" + row.id, None)
        items.append(
            {
                "deployment_id": row.id,
                "revision": row.revision,
                "prediction": snapshot,
                "change_prediction": tx.get_state("change-risk:" + row.id, None),
                "observed_post_rollout": row.outcome,
                "note": "No frozen model snapshot" if snapshot is None else None,
            }
        )
    return {"items": items, "truncated": len(documents) > limit, "authorizes_execution": False}
