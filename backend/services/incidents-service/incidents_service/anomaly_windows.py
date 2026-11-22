"""Detector anomaly samples, bounded and distinct from incident/fault intervals."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from incidents_service.repository import Transaction, state


def windows(
    tx: Transaction, service: str, environment: str, metric: str, at: datetime
) -> dict[str, Any]:
    rows = tx.recent_events(
        service,
        environment,
        "metric",
        limit=5001,
        not_before=at - timedelta(hours=24),
        not_after=at,
    )
    # Detector source samples keep their committed anomaly marker, rather than
    # guessing anomaly intervals from incident creation and eventual closure.
    records = {
        str(key): doc
        for key, doc in tx.conn.execute(
            select(state.c.key, state.c.document).where(
                state.c.key.in_(["anomaly-sample:" + str(row["id"]) for row in rows[:5000]])
            )
        )
    }
    points = []
    for row in rows[:5000]:
        payload = row["payload"]
        if payload.get("name") != metric or payload.get("labels"):
            continue
        record = records.get("anomaly-sample:" + row["id"])
        if record:
            points.append(record)
    return {
        "service": service,
        "environment": environment,
        "metric": metric,
        "points": points,
        "truncated": len(rows) > 5000,
        "scope": "latest5000 metric events in24h, unlabelled aggregate series only",
        "caveat": "Detector-flagged producer samples, not independently measured fault windows. No interpolation or inferred recovery interval.",
    }
