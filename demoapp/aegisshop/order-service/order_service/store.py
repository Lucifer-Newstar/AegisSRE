"""Order persistence, separate from the platform's incident/evidence database."""

from __future__ import annotations

import threading
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    MetaData,
    String,
    Table,
    create_engine,
    delete,
    insert,
    select,
    text,
)
from sqlalchemy.pool import StaticPool

metadata = MetaData()
orders = Table(
    "shop_orders",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("document", JSON, nullable=False),
)


class OrderStore:
    """Lazy schema initialization: a dependency outage must not prevent liveness.

    SQLite is an explicit single-process development/test fallback. Compose and
    kind configure a different PostgreSQL server from the platform database.
    """

    def __init__(self, url: str):
        options: dict[str, Any] = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False, "timeout": 3}
            if ":memory:" in url:
                options["poolclass"] = StaticPool
        elif url.startswith("postgresql+psycopg://"):
            options.update(
                pool_timeout=3,
                connect_args={"connect_timeout": 3, "options": "-c statement_timeout=3000"},
            )
        else:
            raise ValueError("Order storage requires PostgreSQL/psycopg or SQLite")
        self.engine = create_engine(url, **options)
        self._lock = threading.RLock()
        self._initialized = False

    def prepare(self) -> None:
        with self._lock:
            if self._initialized:
                return
            with self.engine.begin() as connection:
                if self.engine.dialect.name == "postgresql":
                    connection.execute(text("SELECT pg_advisory_xact_lock(87020001)"))
                metadata.create_all(connection)
            self._initialized = True

    def ping(self) -> None:
        self.prepare()
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def put(self, order: dict[str, Any]) -> None:
        self.prepare()
        with self._lock, self.engine.begin() as connection:
            connection.execute(insert(orders).values(id=order["id"], document=order))

    def get(self, order_id: str) -> dict[str, Any] | None:
        self.prepare()
        with self._lock, self.engine.connect() as connection:
            value = connection.execute(
                select(orders.c.document).where(orders.c.id == order_id)
            ).scalar_one_or_none()
            return dict(value) if value is not None else None

    def clear(self) -> None:
        """Explicit test helper, never called by application startup or recovery."""
        self.prepare()
        with self._lock, self.engine.begin() as connection:
            connection.execute(delete(orders))

    def close(self) -> None:
        self.engine.dispose()
