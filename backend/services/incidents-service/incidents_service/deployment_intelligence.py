"""Observed deploy windows, never a causal claim or an execution permission.

Explicit deployment_id groups lifecycle events. Repeated revisions alone do not.
Missing identity/evidence and overlapping unlabelled rollouts stay unknown.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import AwareDatetime, Field

from incidents_service.models import Deployment, Event, Metric, Signal, StrictModel, now
from incidents_service.repository import Transaction

WINDOW_SECONDS = 180
TRACKED_METRICS = {"latency_p95", "error_rate", "slo_burn_rate"}
REQUIRED_METRICS = {"latency_p95", "error_rate"}


class DeploymentConflict(ValueError):
    pass


class Rollout(StrictModel):
    workload_uid: str | None = None
    id: str
    service: str
    environment: str
    deployment_id: str | None
    identity_explicit: bool
    revision: str
    previous_revision: str | None
    started_at: AwareDatetime
    anchor_source: Literal["producer_started_at", "first_event_timestamp"]
    window_end: AwareDatetime
    phase: Literal["in_progress", "succeeded", "failed"]
    last_phase_at: AwareDatetime
    outcome: Literal["monitoring", "bad", "healthy", "insufficient"] = "monitoring"
    reason: str = "Awaiting the deployment window and fresh observations"
    source_event_ids: list[str] = Field(default_factory=list)
    observation_ids: list[str] = Field(default_factory=list)
    normal_series: dict[str, str] = Field(default_factory=dict)
    normal_counts: dict[str, int] = Field(default_factory=dict)
    last_normal_at: dict[str, AwareDatetime] = Field(default_factory=dict)
    health_at: AwareDatetime | None = None
    health_ok: bool = False
    ambiguous: bool = False
    flagged_at: AwareDatetime | None = None
    bad_observed_at: AwareDatetime | None = None
    flag_latency_seconds: float | None = None
    incident_id: str | None = None
    revision_number: int = 1
    assessed_at: AwareDatetime | None = None


def _save(tx: Transaction, row: Rollout) -> None:
    tx.save_rollout(row.model_dump(mode="json"))


def _bad(tx: Transaction, row: Rollout, event: Event, reason: str, incident_id: str | None) -> None:
    if row.outcome == "bad":
        return
    clock = now()
    row.outcome, row.reason = "bad", reason
    row.assessed_at = clock
    row.flagged_at, row.bad_observed_at = clock, event.timestamp
    row.flag_latency_seconds = (
        (clock - row.started_at).total_seconds()
        if row.anchor_source == "producer_started_at" and clock >= row.started_at
        else None
    )
    row.incident_id = incident_id
    row.revision_number += 1
    tx.emit(
        {
            "id": "rollout_bad_" + row.id,
            "schema_version": "0.2",
            "timestamp": clock.isoformat(),
            "source": "ml" if event.type == "metric" else "deployment",
            "type": "rollout.bad",
            "service": row.service,
            "environment": row.environment,
            "severity": "warning",
            "payload": {
                "rollout_id": row.id,
                "deployment_id": row.deployment_id,
                "revision": row.revision,
                "status": "bad",
                "reason": reason,
                "observation_id": event.id,
                "observed_at": event.timestamp.isoformat(),
                "flagged_at": clock.isoformat(),
                "flag_latency_seconds": row.flag_latency_seconds,
                "source_event_ids": row.source_event_ids,
                "incident_id": incident_id,
                "causation_proven": False,
                "authorizes_execution": False,
            },
        }
    )
    tx.append_audit(
        incident_id,
        {
            "at": clock.isoformat(),
            "actor": "deployment-window",
            "action": "rollout.bad",
            "detail": "Observed bad deployment window: " + row.id,
        },
        service=row.service,
        environment=row.environment,
    )


def register(tx: Transaction, event: Event) -> None:
    payload = Deployment.model_validate(event.payload)
    if payload.action != "deploy":
        return
    identity = (
        "logical:" + payload.deployment_id
        if payload.deployment_id is not None
        else "event:" + event.id
    )
    key = (
        "dep_"
        + hashlib.sha256(
            (event.service + "\0" + event.environment + "\0" + identity).encode()
        ).hexdigest()
    )
    document = tx.rollout(key)
    row = Rollout.model_validate(document) if document else None
    start = (payload.started_at or event.timestamp).astimezone(UTC)
    if start > event.timestamp:
        raise DeploymentConflict("Deployment start cannot follow its producer event timestamp")
    if row is not None:
        if row.workload_uid != payload.workload_uid:
            raise DeploymentConflict("Deployment identity reused across workload UIDs")
        if row.revision != payload.revision or (
            row.previous_revision is not None
            and payload.previous_revision is not None
            and row.previous_revision != payload.previous_revision
        ):
            raise DeploymentConflict("Deployment identity reused with a different revision")
        if row.previous_revision is None:
            row.previous_revision = payload.previous_revision
        if payload.started_at is not None and row.started_at != start:
            raise DeploymentConflict("Deployment identity reused with a different start")
        if payload.started_at is not None:
            row.anchor_source = "producer_started_at"
            if row.flagged_at is not None and row.flagged_at >= start:
                row.flag_latency_seconds = (row.flagged_at - start).total_seconds()
        if (
            row.phase in {"succeeded", "failed"}
            and payload.status in {"succeeded", "failed"}
            and row.phase != payload.status
        ):
            raise DeploymentConflict("Terminal deployment phase cannot be rewritten")
        if event.timestamp >= row.last_phase_at and (
            row.phase == "in_progress" or payload.status == row.phase
        ):
            row.phase, row.last_phase_at = payload.status, event.timestamp
        row.source_event_ids = list(dict.fromkeys([*row.source_event_ids, event.id]))[-100:]
        row.revision_number += 1
    else:
        row = Rollout(
            id=key,
            workload_uid=payload.workload_uid,
            service=event.service,
            environment=event.environment,
            deployment_id=payload.deployment_id,
            identity_explicit=payload.deployment_id is not None,
            revision=payload.revision,
            previous_revision=payload.previous_revision,
            started_at=start,
            anchor_source="producer_started_at" if payload.started_at else "first_event_timestamp",
            window_end=start + timedelta(seconds=WINDOW_SECONDS),
            phase=payload.status,
            last_phase_at=event.timestamp,
            source_event_ids=[event.id],
        )
    if event.timestamp < row.started_at:
        row.ambiguous = True
        row.reason = "An earlier lifecycle phase arrived without a stable producer start"
    overlaps = tx.list_rollouts(
        service=row.service,
        environment=row.environment,
        limit=501,
        overlap_start=row.started_at,
        overlap_end=row.window_end,
    )
    if len(overlaps) > 500:
        row.ambiguous = True
    for document in overlaps:
        other = Rollout.model_validate(document)
        if other.id != row.id:
            row.ambiguous = other.ambiguous = True
            _save(tx, other)
    if payload.status == "failed":
        _bad(tx, row, event, "Producer reported an actual rollout failure", None)
    _save(tx, row)
    tx.map_rollout_event(event.id, row.id)
    from incidents_service.change_risk import bind
    from incidents_service.deployment_risk import score

    bind(tx, row, payload.change_attributes)

    if tx.get_state("risk:" + row.id, None) is None:
        tx.put_state("risk:" + row.id, score(tx, row))


def observe(
    tx: Transaction,
    event: Event,
    signal: Signal | None,
    baseline_ready: bool,
    incident_id: str | None,
) -> None:
    if event.type not in {"metric", "health"}:
        return
    candidates = [
        Rollout.model_validate(item)
        for item in tx.list_rollouts(
            service=event.service,
            environment=event.environment,
            limit=501,
            active_at=event.timestamp,
        )
    ]
    if len(candidates) > 500:
        return  # Incomplete identity snapshot cannot select a rollout safely.
    metric = Metric.model_validate(event.payload) if event.type == "metric" else None
    revision = metric.labels.get("revision") if metric else None
    if metric and set(metric.labels) - {"revision"}:
        return  # Do not combine canary/instance series with aggregate baselines.
    if revision:
        candidates = [row for row in candidates if row.revision == revision]
    if len(candidates) != 1:
        for row in candidates:
            row.ambiguous = True
            row.reason = "Overlapping rollouts cannot be attributed from unscoped observations"
            _save(tx, row)
        return
    row = candidates[0]
    if row.outcome in {"healthy", "insufficient"}:
        row.outcome = "monitoring"  # Late evidence requires re-evaluation, never stale health.
    row.observation_ids = list(dict.fromkeys([*row.observation_ids, event.id]))[-100:]
    if metric and metric.name in TRACKED_METRICS:
        if row.normal_series.get(metric.name) != event.series() or not baseline_ready:
            row.normal_counts[metric.name] = 0
            row.last_normal_at.pop(metric.name, None)
        row.normal_series[metric.name] = event.series()
        if signal is not None:
            row.normal_counts[metric.name] = 0
            _bad(
                tx,
                row,
                event,
                "Baseline-qualified anomalous " + metric.name + " inside the deployment window",
                incident_id,
            )
        elif baseline_ready:
            row.normal_counts[metric.name] = min(1000, row.normal_counts.get(metric.name, 0) + 1)
            row.last_normal_at[metric.name] = event.timestamp
    elif event.type == "health" and (row.health_at is None or event.timestamp > row.health_at):
        row.health_at = event.timestamp
        row.health_ok = event.payload.get("status") == "healthy" and all(
            event.payload.get(key) is True for key in ("slo_ok", "errors_ok", "latency_ok")
        )
    row.revision_number += 1
    _save(tx, row)


def finalize(tx: Transaction, clock: datetime | None = None) -> None:
    point = clock or now()
    if point.tzinfo is None:
        raise ValueError("Rollout finalization requires an aware clock")
    for document in tx.list_rollouts(
        outcome="monitoring", ended_before=point - timedelta(seconds=15), limit=5000
    ):
        row = Rollout.model_validate(document)
        if point < row.window_end + timedelta(seconds=15):
            continue
        cutoff = row.window_end - timedelta(seconds=45)
        metrics_good = all(
            row.normal_counts.get(name, 0) >= 3
            and row.last_normal_at.get(name, row.started_at) >= cutoff
            for name in REQUIRED_METRICS
        )
        health_good = row.health_ok and row.health_at is not None and row.health_at >= cutoff
        row.assessed_at = point
        row.outcome = (
            "healthy"
            if metrics_good
            and health_good
            and not row.ambiguous
            and row.phase == "succeeded"
            and row.anchor_source == "producer_started_at"
            else "insufficient"
        )
        row.reason = (
            "Fresh end-window health and baseline-qualified samples passed"
            if row.outcome == "healthy"
            else "Window ended without complete unambiguous health/metric/phase evidence"
        )
        row.revision_number += 1
        _save(tx, row)


def summary(tx: Transaction, *, service: str, environment: str, since: datetime) -> dict[str, Any]:
    point = now()
    counts = tx.rollout_counts(service, environment, since, point)
    explicit = counts["identified"]
    bad, healthy = counts["bad"], counts["healthy"]
    unknown = explicit - bad - healthy
    legacy = counts["unidentified"] + counts["unmapped_events"]
    return {
        "service": service,
        "environment": environment,
        "since": since.isoformat(),
        "as_of": point.isoformat(),
        "counting_unit": "explicit deployment_id, scoped by service and environment; deploy actions only",
        "identified_deployments": explicit,
        "confirmed_bad": bad,
        "observed_healthy": healthy,
        "unknown_outcomes": unknown,
        "unidentified_or_unmapped_events": legacy,
        "change_failure_rate": bad / explicit if explicit and not unknown and not legacy else None,
        "observed_finalized_rate": bad / (bad + healthy) if bad + healthy else None,
        "outcome_coverage": (bad + healthy) / explicit if explicit else None,
        "identified_failure_lower_bound": bad / explicit if explicit else None,
        "identified_failure_upper_bound": (bad + unknown) / explicit if explicit else None,
        "caveat": "Observed outcomes, not evaluation ground truth. Missing identity/outcomes are not healthy. Legacy event counts cannot establish a logical deployment denominator. Temporal association is not proof of causation.",
    }
