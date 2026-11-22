"""Small durable document store for catalogue/deployment metadata.

Keys and namespaces are bound values, never SQL identifiers. PostgreSQL
transactions serialize read/modify/write decisions with an advisory lock.
SQLite is the independent single-process local/test backend.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
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
    update,
)
from sqlalchemy.pool import StaticPool

metadata = MetaData()
documents = Table(
    "aegis_documents",
    metadata,
    Column("namespace", String(100), primary_key=True),
    Column("key", String(200), primary_key=True),
    Column("document", JSON, nullable=False),
)


class DocumentStore:
    def __init__(self, namespace: str, url: str = "sqlite:///:memory:"):
        self.namespace = namespace
        self.lock = threading.RLock()
        options: dict[str, Any] = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False, "timeout": 30}
            if ":memory:" in url:
                options["poolclass"] = StaticPool
        self.engine = create_engine(url, **options)
        with self.engine.begin() as connection:
            if self.engine.dialect.name == "postgresql":
                connection.execute(text("SELECT pg_advisory_xact_lock(87010000)"))
            metadata.create_all(connection)

    def get(self, key: str) -> dict[str, Any] | None:
        with self.lock, self.engine.connect() as connection:
            row = connection.execute(
                select(documents.c.document).where(
                    documents.c.namespace == self.namespace, documents.c.key == key
                )
            ).scalar_one_or_none()
            return dict(row) if row is not None else None

    def mutate(
        self, key: str, change: Callable[[dict[str, Any] | None], dict[str, Any] | None]
    ) -> dict[str, Any] | None:
        with self.lock, self.engine.begin() as connection:
            if self.engine.dialect.name == "postgresql":
                connection.execute(text("SELECT pg_advisory_xact_lock(87010001)"))
            where = (documents.c.namespace == self.namespace) & (documents.c.key == key)
            previous = connection.execute(
                select(documents.c.document).where(where)
            ).scalar_one_or_none()
            result = change(dict(previous) if previous is not None else None)
            if result is None:
                connection.execute(delete(documents).where(where))
            elif previous is None:
                connection.execute(
                    insert(documents).values(namespace=self.namespace, key=key, document=result)
                )
            else:
                connection.execute(update(documents).where(where).values(document=result))
            return result

    def put(
        self, key: str, value: dict[str, Any], *, if_absent: bool = False
    ) -> tuple[dict[str, Any], bool]:
        created = False

        def change(previous: dict[str, Any] | None) -> dict[str, Any]:
            nonlocal created
            created = previous is None
            return previous if if_absent and previous is not None else value

        result = self.mutate(key, change)
        assert result is not None
        return result, created

    def list(self) -> list[dict[str, Any]]:
        with self.lock, self.engine.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    select(documents.c.document).where(documents.c.namespace == self.namespace)
                ).scalars()
            ]

    def delete(self, key: str) -> bool:
        existed = False

        def remove(previous: dict[str, Any] | None) -> None:
            nonlocal existed
            existed = previous is not None

        self.mutate(key, remove)
        return existed

    def clear(self) -> None:
        """Explicit test/administrative operation. Never called automatically."""
        with self.lock, self.engine.begin() as connection:
            connection.execute(delete(documents).where(documents.c.namespace == self.namespace))

    def ping(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def close(self) -> None:
        self.engine.dispose()
