"""Observed CFR cohorts. Unknown cohorts have gaps, never zero failure rates."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from incidents_service.deployment_intelligence import Rollout
from incidents_service.repository import Transaction


def trend(tx: Transaction, service: str, environment: str, at: datetime) -> dict[str, Any]:
    end = at.astimezone(UTC)
    start = end.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=29)
    points = []
    for index in range(30):
        lower = start + timedelta(days=index)
        upper = min(lower + timedelta(days=1) - timedelta(microseconds=1), end)
        counts = tx.rollout_counts(service, environment, lower, upper)
        total, bad, healthy = counts["identified"], counts["bad"], counts["healthy"]
        unknown = total - bad - healthy
        unidentified = counts["unidentified"] + counts["unmapped_events"]
        points.append(
            {
                "start": lower.isoformat(),
                "end": upper.isoformat(),
                "identified": total,
                "bad": bad,
                "healthy": healthy,
                "unknown": unknown,
                "unidentified_or_unmapped": unidentified,
                "cfr": bad / total if total and not unknown and not unidentified else None,
                "coverage": (bad + healthy) / total if total else None,
            }
        )
    return {
        "service": service,
        "environment": environment,
        "as_of": end.isoformat(),
        "points": points,
        "caveat": "UTC deployment-start cohorts, observed outcomes as of this read, not historical snapshots or causal attribution. Empty or incomplete cohorts are gaps, never zero. Late evidence may revise prior days.",
    }


def report(
    tx: Transaction, rollout_id: str, service: str, environment: str
) -> dict[str, Any] | None:
    document = tx.rollout(rollout_id)
    if document is None:
        return None
    row = Rollout.model_validate(document)
    if row.service != service or row.environment != environment:
        return None
    incident = tx.incident(row.incident_id) if row.incident_id else None
    # Do not cross a boundary merely because a stored relation says to.
    if incident and (incident.service != service or incident.environment != environment):
        incident = None
    return {
        "rollout": row.model_dump(mode="json"),
        "frozen_risk": tx.get_state("risk:" + row.id, None),
        "incident_status": incident.status if incident else None,
        "actions": [
            a.model_dump(mode="json") for a in incident.audit if a.action.startswith("remediation.")
        ]
        if incident
        else [],
        "incident_report_available": bool(incident and incident.status == "closed"),
        "source_event_ids": row.source_event_ids,
        "observation_ids": row.observation_ids,
        "caveat": "Observed deployment review, not an AI-authored causal postmortem or independent ground truth. Incident report is available only after closure; missing actions and recovery are not invented.",
    }
