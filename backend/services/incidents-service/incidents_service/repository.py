"""Transactional persistence and an outbox. Postgres in Compose, SQLite for unit tests.

A single transaction covers deduplication, baselines, incident changes and audit.
Postgres advisory transaction locks serialize loop decisions across API/worker
processes. SQLite runs one process and uses a process-local lock.
"""
from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    delete,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.engine import Connection
from sqlalchemy.pool import StaticPool

from incidents_service.models import Event, Incident, Metric

metadata = MetaData()
events = Table("aegis_events", metadata,
    Column("id", String(160), primary_key=True),
    Column("service", String(63), index=True, nullable=False),
    Column("environment", String(40), nullable=False),
    Column("type", String(30), nullable=False),
    Column("timestamp", String(40), nullable=False),
    Column("series", String(64), index=True),
    Column("value", Float),
    Column("normal", Boolean, nullable=False, default=False),
    Column("document", JSON, nullable=False))
incidents = Table("aegis_incidents", metadata,
    Column("id", String(80), primary_key=True),
    Column("service", String(63), index=True, nullable=False),
    Column("environment", String(40), nullable=False),
    Column("status", String(30), nullable=False),
    Column("document", JSON, nullable=False))
audit = Table("aegis_audit", metadata,
    Column("seq", Integer, primary_key=True, autoincrement=True),
    Column("incident_id", String(80), index=True),
    Column("document", JSON, nullable=False))
state = Table("aegis_state", metadata,
    Column("key", String(160), primary_key=True), Column("document", JSON, nullable=False))
outbox = Table("aegis_outbox", metadata,
    Column("seq", Integer, primary_key=True, autoincrement=True),
    Column("document", JSON, nullable=False))


class Transaction:
    def __init__(self, connection: Connection):
        self.conn = connection

    def event(self, event_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(select(events.c.document).where(events.c.id == event_id)).scalar_one_or_none()
        return dict(row) if row is not None else None

    def add_event(self, event: Event, normal: bool = False) -> None:
        metric = Metric.model_validate(event.payload) if event.type == "metric" else None
        self.conn.execute(insert(events).values(
            id=event.id, service=event.service, environment=event.environment, type=event.type,
            timestamp=event.timestamp.isoformat(), series=event.series() if metric else None,
            value=metric.value if metric else None, normal=normal, document=event.model_dump(mode="json")))

    def baseline(self, series: str, limit: int = 60) -> list[float]:
        rows = self.conn.execute(select(events.c.value).where(
            events.c.series == series, events.c.normal.is_(True))
            .order_by(events.c.timestamp.desc()).limit(limit)).scalars().all()
        return [float(v) for v in reversed(rows)]

    def latest_sample(self, series: str) -> dict[str, Any] | None:
        row = self.conn.execute(select(events.c.document).where(events.c.series == series)
            .order_by(events.c.timestamp.desc()).limit(1)).scalar_one_or_none()
        return dict(row) if row is not None else None

    def recent_events(self, service: str | None = None, environment: str | None = None,
                      event_type: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = select(events.c.document)
        if service is not None:
            query = query.where(events.c.service == service)
        if environment is not None:
            query = query.where(events.c.environment == environment)
        if event_type is not None:
            query = query.where(events.c.type == event_type)
        return [dict(row) for row in self.conn.execute(query.order_by(events.c.timestamp.desc()).limit(limit)).scalars()]

    def incident(self, incident_id: str) -> Incident | None:
        row = self.conn.execute(select(incidents.c.document).where(incidents.c.id == incident_id)).scalar_one_or_none()
        return Incident.model_validate(row) if row is not None else None

    def list_incidents(self, service: str | None = None, limit: int = 100) -> list[Incident]:
        query = select(incidents.c.document)
        if service is not None:
            query = query.where(incidents.c.service == service)
        return [Incident.model_validate(row) for row in self.conn.execute(
            query.order_by(incidents.c.id.desc()).limit(limit)).scalars()]

    def active_incident(self, service: str, environment: str) -> Incident | None:
        row = self.conn.execute(select(incidents.c.document).where(
            incidents.c.service == service, incidents.c.environment == environment,
            incidents.c.status.not_in(["closed", "escalated"])).limit(1)).scalar_one_or_none()
        return Incident.model_validate(row) if row is not None else None

    def save_incident(self, item: Incident) -> None:
        exists = self.conn.execute(select(incidents.c.id).where(incidents.c.id == item.id)).first()
        values = {"service": item.service, "environment": item.environment,
                  "status": item.status, "document": item.model_dump(mode="json")}
        if exists:
            self.conn.execute(update(incidents).where(incidents.c.id == item.id).values(**values))
        else:
            self.conn.execute(insert(incidents).values(id=item.id, **values))

    def append_audit(self, incident_id: str | None, document: dict[str, Any]) -> None:
        self.conn.execute(insert(audit).values(incident_id=incident_id, document=document))

    def audits(self, incident_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        query = select(audit.c.seq, audit.c.incident_id, audit.c.document)
        if incident_id is not None:
            query = query.where(audit.c.incident_id == incident_id)
        return [{"seq": row.seq, "incident_id": row.incident_id, **row.document}
                for row in self.conn.execute(query.order_by(audit.c.seq.desc()).limit(limit))]

    def get_state(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute(select(state.c.document).where(state.c.key == key)).scalar_one_or_none()
        return default if row is None else row

    def put_state(self, key: str, document: Any) -> None:
        exists = self.conn.execute(select(state.c.key).where(state.c.key == key)).first()
        if exists:
            self.conn.execute(update(state).where(state.c.key == key).values(document=document))
        else:
            self.conn.execute(insert(state).values(key=key, document=document))

    def emit(self, document: dict[str, Any]) -> None:
        self.conn.execute(insert(outbox).values(document=document))

    def pending(self, limit: int = 100) -> list[tuple[int, dict[str, Any]]]:
        return [(row.seq, dict(row.document)) for row in self.conn.execute(
            select(outbox).order_by(outbox.c.seq).limit(limit))]

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
        metadata.create_all(self.engine)

    @contextmanager
    def transaction(self) -> Iterator[Transaction]:
        with self.lock, self.engine.begin() as connection:
            if self.engine.dialect.name == "postgresql":
                connection.execute(text("SELECT pg_advisory_xact_lock(87018201)"))
            yield Transaction(connection)

    def close(self) -> None:
        self.engine.dispose()
