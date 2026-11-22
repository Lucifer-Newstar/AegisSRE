"""Transactional persistence and an outbox. Postgres in Compose, SQLite for unit tests.

A single transaction covers deduplication, baselines, incident changes and audit.
Postgres advisory transaction locks serialize loop decisions across API/worker
processes. SQLite runs one process and uses a process-local lock.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    and_,
    case,
    cast,
    create_engine,
    delete,
    func,
    insert,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.engine import Connection
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql.elements import ColumnElement

from incidents_service.models import Event, Incident, Metric

metadata = MetaData()
events = Table(
    "aegis_events",
    metadata,
    Column("id", String(160), primary_key=True),
    Column("service", String(63), index=True, nullable=False),
    Column("environment", String(40), nullable=False),
    Column("type", String(30), nullable=False),
    Column("timestamp", String(40), nullable=False),
    Column("series", String(64), index=True),
    Column("value", Float),
    Column("normal", Boolean, nullable=False, default=False),
    Column("document", JSON, nullable=False),
)
incidents = Table(
    "aegis_incidents",
    metadata,
    Column("id", String(80), primary_key=True),
    Column("service", String(63), index=True, nullable=False),
    Column("environment", String(40), nullable=False),
    Column("status", String(30), nullable=False),
    Column("document", JSON, nullable=False),
)
audit = Table(
    "aegis_audit",
    metadata,
    Column("seq", Integer, primary_key=True, autoincrement=True),
    Column("incident_id", String(80), index=True),
    Column("document", JSON, nullable=False),
)
state = Table(
    "aegis_state",
    metadata,
    Column("key", String(160), primary_key=True),
    Column("document", JSON, nullable=False),
)
outbox = Table(
    "aegis_outbox",
    metadata,
    Column("seq", Integer, primary_key=True, autoincrement=True),
    Column("document", JSON, nullable=False),
)


rollouts = Table(
    "aegis_rollouts",
    metadata,
    Column("id", String(80), primary_key=True),
    Column("service", String(63), index=True, nullable=False),
    Column("environment", String(40), index=True, nullable=False),
    Column("started_at", DateTime(timezone=True), index=True, nullable=False),
    Column("window_end", DateTime(timezone=True), nullable=False),
    Column("outcome", String(20), index=True, nullable=False),
    Column("phase", String(20), nullable=False),
    Column("ambiguous", Boolean, nullable=False),
    Column("identity_explicit", Boolean, nullable=False),
    Column("document", JSON, nullable=False),
)
rollout_events = Table(
    "aegis_rollout_events",
    metadata,
    Column("event_id", String(160), primary_key=True),
    Column("rollout_id", String(80), nullable=False),
)


class Transaction:
    def __init__(self, connection: Connection):
        self.conn = connection

    @property
    def event_time(self) -> ColumnElement[Any]:
        # Older records can carry equivalent timestamps with different offsets.
        # Compare instants, not lexicographic ISO strings. No data rewrite needed.
        if self.conn.dialect.name == "sqlite":
            return func.julianday(events.c.timestamp)
        return cast(events.c.timestamp, DateTime(timezone=True))

    def event(self, event_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            select(events.c.document).where(events.c.id == event_id)
        ).scalar_one_or_none()
        return dict(row) if row is not None else None

    def add_event(self, event: Event, normal: bool = False) -> None:
        event = event.model_copy(update={"timestamp": event.timestamp.astimezone(UTC)})
        metric = Metric.model_validate(event.payload) if event.type == "metric" else None
        self.conn.execute(
            insert(events).values(
                id=event.id,
                service=event.service,
                environment=event.environment,
                type=event.type,
                timestamp=event.timestamp.isoformat(),
                series=event.series() if metric else None,
                value=metric.value if metric else None,
                normal=normal,
                document=event.model_dump(mode="json"),
            )
        )

    def baseline_samples(self, series: str, limit: int = 60) -> list[tuple[str, float]]:
        rows = self.conn.execute(
            select(events.c.timestamp, events.c.value)
            .where(events.c.series == series, events.c.normal.is_(True))
            .order_by(self.event_time.desc(), events.c.id.desc())
            .limit(limit)
        ).all()
        return [(str(row.timestamp), float(row.value)) for row in reversed(rows)]

    def baseline(self, series: str, limit: int = 60) -> list[float]:
        return [value for _, value in self.baseline_samples(series, limit)]

    def latest_sample(self, series: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            select(events.c.document)
            .where(events.c.series == series)
            .order_by(self.event_time.desc(), events.c.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        return dict(row) if row is not None else None

    def recent_events(
        self,
        service: str | None = None,
        environment: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
        *,
        not_before: datetime | None = None,
        not_after: datetime | None = None,
    ) -> list[dict[str, Any]]:
        query = select(events.c.document)
        if service is not None:
            query = query.where(events.c.service == service)
        if environment is not None:
            query = query.where(events.c.environment == environment)
        if event_type is not None:
            query = query.where(events.c.type == event_type)
        for bound, lower in ((not_before, True), (not_after, False)):
            if bound is not None:
                if bound.tzinfo is None:
                    raise ValueError("Evidence window bounds require timezones")
                instant = bound.astimezone(UTC)
                value = (
                    func.julianday(instant.isoformat())
                    if self.conn.dialect.name == "sqlite"
                    else instant
                )
                query = query.where(self.event_time >= value if lower else self.event_time <= value)
        return [
            dict(row)
            for row in self.conn.execute(
                query.order_by(self.event_time.desc(), events.c.id.desc()).limit(limit)
            ).scalars()
        ]

    def rollout(self, rollout_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            select(rollouts.c.document).where(rollouts.c.id == rollout_id)
        ).scalar_one_or_none()
        return dict(row) if row is not None else None

    def save_rollout(self, document: dict[str, Any]) -> None:
        values = {
            name: document[name]
            for name in (
                "service",
                "environment",
                "outcome",
                "phase",
                "ambiguous",
                "identity_explicit",
            )
        }
        values.update(
            {
                name: datetime.fromisoformat(document[name]).astimezone(UTC)
                for name in ("started_at", "window_end")
            }
        )
        values["document"] = document
        if self.rollout(str(document["id"])) is None:
            self.conn.execute(insert(rollouts).values(id=document["id"], **values))
        else:
            self.conn.execute(
                update(rollouts).where(rollouts.c.id == document["id"]).values(**values)
            )

    def map_rollout_event(self, event_id: str, rollout_id: str) -> None:
        self.conn.execute(insert(rollout_events).values(event_id=event_id, rollout_id=rollout_id))

    def list_rollouts(
        self,
        *,
        service: str | None = None,
        environment: str | None = None,
        outcome: str | None = None,
        limit: int = 100,
        active_at: datetime | None = None,
        ended_before: datetime | None = None,
        overlap_start: datetime | None = None,
        overlap_end: datetime | None = None,
    ) -> list[dict[str, Any]]:
        query = select(rollouts.c.document)
        for column, value in (
            (rollouts.c.service, service),
            (rollouts.c.environment, environment),
            (rollouts.c.outcome, outcome),
        ):
            if value is not None:
                query = query.where(column == value)
        if active_at is not None:
            point = active_at.astimezone(UTC)
            query = query.where(rollouts.c.started_at <= point, rollouts.c.window_end >= point)
        if ended_before is not None:
            query = query.where(rollouts.c.window_end <= ended_before.astimezone(UTC))
        if overlap_start is not None and overlap_end is not None:
            query = query.where(
                rollouts.c.started_at <= overlap_end.astimezone(UTC),
                rollouts.c.window_end >= overlap_start.astimezone(UTC),
            )
        return [
            dict(row)
            for row in self.conn.execute(
                query.order_by(rollouts.c.started_at.desc(), rollouts.c.id.desc()).limit(
                    max(1, min(limit, 5001))
                )
            ).scalars()
        ]

    def rollout_counts(
        self, service: str, environment: str, since: datetime, until: datetime
    ) -> dict[str, int]:
        known_bad = and_(
            rollouts.c.outcome == "bad",
            or_(rollouts.c.ambiguous.is_(False), rollouts.c.phase == "failed"),
        )
        known_healthy = and_(rollouts.c.outcome == "healthy", rollouts.c.ambiguous.is_(False))
        identified = rollouts.c.identity_explicit.is_(True)
        expressions = {
            "identified": identified,
            "unidentified": rollouts.c.identity_explicit.is_(False),
            "bad": and_(identified, known_bad),
            "healthy": and_(identified, known_healthy),
        }
        result = (
            self.conn.execute(
                select(
                    *(
                        func.sum(case((expression, 1), else_=0)).label(name)
                        for name, expression in expressions.items()
                    )
                ).where(
                    rollouts.c.service == service,
                    rollouts.c.environment == environment,
                    rollouts.c.started_at >= since.astimezone(UTC),
                    rollouts.c.started_at <= until.astimezone(UTC),
                )
            )
            .mappings()
            .one()
        )
        counts = {name: int(result[name] or 0) for name in expressions}
        bound = (
            func.julianday(since.astimezone(UTC).isoformat())
            if self.conn.dialect.name == "sqlite"
            else since.astimezone(UTC)
        )
        upper = (
            func.julianday(until.astimezone(UTC).isoformat())
            if self.conn.dialect.name == "sqlite"
            else until.astimezone(UTC)
        )
        missing = self.conn.execute(
            select(func.count())
            .select_from(events)
            .where(
                events.c.service == service,
                events.c.environment == environment,
                events.c.type == "deployment",
                events.c.document["payload"]["action"].as_string() == "deploy",
                self.event_time >= bound,
                self.event_time <= upper,
                ~select(rollout_events.c.event_id)
                .where(rollout_events.c.event_id == events.c.id)
                .exists(),
            )
        ).scalar_one()
        counts["unmapped_events"] = int(missing)
        return counts

    def incident(self, incident_id: str) -> Incident | None:
        row = self.conn.execute(
            select(incidents.c.document).where(incidents.c.id == incident_id)
        ).scalar_one_or_none()
        return Incident.model_validate(row) if row is not None else None

    def list_incidents(self, service: str | None = None, limit: int = 100) -> list[Incident]:
        query = select(incidents.c.document)
        if service is not None:
            query = query.where(incidents.c.service == service)
        return [
            Incident.model_validate(row)
            for row in self.conn.execute(
                query.order_by(incidents.c.id.desc()).limit(limit)
            ).scalars()
        ]

    def active_incident(self, service: str, environment: str) -> Incident | None:
        row = self.conn.execute(
            select(incidents.c.document)
            .where(
                incidents.c.service == service,
                incidents.c.environment == environment,
                incidents.c.status.not_in(["closed", "escalated"]),
            )
            .limit(1)
        ).scalar_one_or_none()
        return Incident.model_validate(row) if row is not None else None

    def save_incident(self, item: Incident) -> None:
        exists = self.conn.execute(select(incidents.c.id).where(incidents.c.id == item.id)).first()
        values = {
            "service": item.service,
            "environment": item.environment,
            "status": item.status,
            "document": item.model_dump(mode="json"),
        }
        if exists:
            self.conn.execute(update(incidents).where(incidents.c.id == item.id).values(**values))
        else:
            self.conn.execute(insert(incidents).values(id=item.id, **values))

    def append_audit(
        self,
        incident_id: str | None,
        document: dict[str, Any],
        *,
        service: str = "incidents-service",
        environment: str = "dev",
    ) -> None:
        self.conn.execute(insert(audit).values(incident_id=incident_id, document=document))
        action = str(document.get("action", "unknown"))
        outcome = (
            "denied"
            if action.endswith("denied")
            else "failed"
            if action.endswith("failed")
            else "success"
        )
        self.emit(
            {
                "id": f"audit_{uuid.uuid4().hex}",
                "schema_version": "0.2",
                "timestamp": document.get("at", datetime.now(UTC).isoformat()),
                "source": "policy",
                "type": "audit",
                "service": service,
                "environment": environment,
                "severity": "info" if outcome == "success" else "warning",
                "payload": {
                    "actor": str(document.get("actor", "system")),
                    "action": action,
                    "target": incident_id or "platform",
                    "outcome": outcome,
                    "reason": str(document.get("detail", "")),
                },
            }
        )

    def audits(self, incident_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        query = select(audit.c.seq, audit.c.incident_id, audit.c.document)
        if incident_id is not None:
            query = query.where(audit.c.incident_id == incident_id)
        return [
            {"seq": row.seq, "incident_id": row.incident_id, **row.document}
            for row in self.conn.execute(query.order_by(audit.c.seq.desc()).limit(limit))
        ]

    def get_state(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute(
            select(state.c.document).where(state.c.key == key)
        ).scalar_one_or_none()
        return default if row is None else row

    def put_state(self, key: str, document: Any) -> None:
        exists = self.conn.execute(select(state.c.key).where(state.c.key == key)).first()
        if exists:
            self.conn.execute(update(state).where(state.c.key == key).values(document=document))
        else:
            self.conn.execute(insert(state).values(key=key, document=document))

    def emit(self, document: dict[str, Any]) -> None:
        self.conn.execute(insert(outbox).values(document=document))

    def queued_event(self, event_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            select(outbox.c.document)
            .where(outbox.c.document["id"].as_string() == event_id)
            .limit(1)
        ).scalar_one_or_none()
        return dict(row) if row is not None else None

    def pending(self, limit: int = 100) -> list[tuple[int, dict[str, Any]]]:
        return [
            (row.seq, dict(row.document))
            for row in self.conn.execute(select(outbox).order_by(outbox.c.seq).limit(limit))
        ]

    def delivered(self, seq: int) -> None:
        self.conn.execute(delete(outbox).where(outbox.c.seq == seq))


class Repository:
    def __init__(self, url: str):
        self.lock = threading.RLock()
        options: dict[str, Any] = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False, "timeout": 30}
            if ":memory:" in url:
                options["poolclass"] = StaticPool
        self.engine = create_engine(url, **options)
        with self.engine.begin() as connection:
            if self.engine.dialect.name == "postgresql":
                connection.execute(text("SELECT pg_advisory_xact_lock(87018200)"))
            metadata.create_all(connection)

    @contextmanager
    def transaction(self) -> Iterator[Transaction]:
        with self.lock, self.engine.begin() as connection:
            if self.engine.dialect.name == "postgresql":
                connection.execute(text("SELECT pg_advisory_xact_lock(87018201)"))
            yield Transaction(connection)

    def close(self) -> None:
        self.engine.dispose()
