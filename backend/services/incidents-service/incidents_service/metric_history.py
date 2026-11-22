"""Bounded persisted metric history, never fabricated zero-fill or SLO budgets."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from incidents_service.models import Metric
from incidents_service.repository import Transaction, events

METRICS = {"latency_p95", "error_rate", "request_rate", "cpu_usage_percent", "memory_bytes", "up"}


def history(tx: Transaction, service: str, environment: str, metric: str,
            at: datetime, hours: int, buckets: int) -> dict[str, Any]:
    if metric not in METRICS or not 1 <= hours <= 24 or not 12 <= buckets <= 600:
        raise ValueError("Unsupported metric or history bounds")
    start = at.astimezone(UTC) - timedelta(hours=hours)
    instant = tx.event_time
    lower = start if tx.conn.dialect.name != "sqlite" else start.isoformat()
    if tx.conn.dialect.name == "sqlite":
        from sqlalchemy import func
        lower_value: Any = func.julianday(lower)
        upper_value: Any = func.julianday(at.isoformat())
    else:
        lower_value, upper_value = start, at
    query = (select(events.c.document).where(
        events.c.service == service, events.c.environment == environment,
        events.c.type == "metric", instant >= lower_value, instant <= upper_value,
        events.c.document["payload"]["name"].as_string() == metric,
        events.c.document["source"].as_string() == "prometheus",
    ).order_by(instant.desc(), events.c.id.desc()).limit(12001))
    rows = list(tx.conn.execute(query).scalars())
    truncated = len(rows) > 12000
    groups: dict[int, list[tuple[float, str]]] = {}
    units: set[str] = set()
    width = hours * 3600 / buckets
    for row in rows[:12000]:
        value = Metric.model_validate(row["payload"])
        # Baseline aggregate only. Do not silently mix instance/revision/canary
        # series into a service-wide chart or call sparse data complete.
        if value.labels:
            continue
        point = datetime.fromisoformat(str(row["timestamp"]).replace("Z", "+00:00"))
        index = min(buckets - 1, int((point - start).total_seconds() / width))
        if index < 0:
            continue
        units.add(value.unit)
        groups.setdefault(index, []).append((value.value, str(row["id"])))
    incompatible = len(units) > 1
    points = [] if incompatible else [
        {"at": (start + timedelta(seconds=index * width)).isoformat(),
         "mean": sum(v for v, _ in values) / len(values),
         "min": min(v for v, _ in values), "max": max(v for v, _ in values),
         "samples": len(values), "evidence_id": values[0][1]}
        for index, values in sorted(groups.items())
    ]
    return {"service": service, "environment": environment, "metric": metric,
            "start": start.isoformat(), "end": at.isoformat(), "bucket_seconds": width,
            "unit": next(iter(units)) if len(units) == 1 else None,
            "points": points, "truncated": truncated,
            "status": "incompatible_units" if incompatible else "observed" if points else "no_data",
            "missing_buckets": buckets - len(points), "source": "persisted-prometheus",
            "note": "Bucket mean/min/max of observed aggregate samples only. Missing buckets are gaps, not zero. No interpolation, retention guarantee or long-window SLO claim."}
