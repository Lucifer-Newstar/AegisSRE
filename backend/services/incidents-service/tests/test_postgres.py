"""Optional real PostgreSQL tests, also run in the hosted storage CI job."""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from incidents_service.config import Settings
from incidents_service.engine import ReliabilityLoop
from incidents_service.models import Event
from incidents_service.repository import Repository

DATABASE_URL = os.getenv("AEGIS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AEGIS_TEST_DATABASE_URL not configured")


def test_postgres_transactions_serialize_duplicate_ingestion() -> None:
    with ThreadPoolExecutor(max_workers=4) as constructors:
        repositories = list(constructors.map(lambda _: Repository(DATABASE_URL), range(4)))
    loops = [ReliabilityLoop(repo, Settings(dev_mode=True)) for repo in repositories]
    event = Event(
        id=f"pg-{uuid.uuid4().hex}",
        source="prometheus",
        type="metric",
        service="storage-test",
        payload={"name": "latency", "value": 0.1, "labels": {"run": uuid.uuid4().hex}},
    )
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda loop: loop.ingest(event.model_copy(deep=True)), loops))
        assert sum(not result["duplicate"] for result in results) == 1
        with repositories[0].transaction() as tx:
            assert tx.baseline(event.series()) == [0.1]
        with pytest.raises(RuntimeError), repositories[0].transaction() as tx:
            tx.put_state(event.id, {"must": "roll back"})
            raise RuntimeError("interrupted transaction")
        with repositories[1].transaction() as tx:
            assert tx.get_state(event.id) is None
    finally:
        for repo in repositories:
            repo.close()


def test_postgres_historical_windows_compare_offsets_as_instants() -> None:
    from datetime import timedelta, timezone

    from incidents_service.models import now
    from incidents_service.repository import events
    from sqlalchemy import update

    repo = Repository(DATABASE_URL)
    environment = "window-" + uuid.uuid4().hex[:8]
    clock = now()
    older = Event(
        id="old-" + uuid.uuid4().hex,
        source="prometheus",
        type="metric",
        service="catalog-service",
        environment=environment,
        timestamp=clock - timedelta(seconds=90),
        payload={"name": "window_metric", "value": 1},
    )
    newer = older.model_copy(
        update={
            "id": "new-" + uuid.uuid4().hex,
            "timestamp": clock - timedelta(seconds=30),
            "payload": {"name": "window_metric", "value": 2},
        }
    )
    legacy = older.model_copy(
        update={"timestamp": older.timestamp.astimezone(timezone(timedelta(hours=5, minutes=30)))}
    )
    try:
        with repo.transaction() as tx:
            tx.add_event(older, normal=True)
            tx.add_event(newer, normal=True)
            tx.conn.execute(
                update(events)
                .where(events.c.id == older.id)
                .values(
                    timestamp=legacy.timestamp.isoformat(), document=legacy.model_dump(mode="json")
                )
            )
            assert [item["id"] for item in tx.recent_events("catalog-service", environment)] == [
                newer.id,
                older.id,
            ]
            assert [
                item["id"]
                for item in tx.recent_events(
                    "catalog-service", environment, not_after=clock - timedelta(seconds=60)
                )
            ] == [older.id]
            assert [
                item["id"]
                for item in tx.recent_events(
                    "catalog-service", environment, not_before=clock - timedelta(seconds=60)
                )
            ] == [newer.id]
            assert tx.baseline(newer.series()) == [1, 2]
    finally:
        repo.close()
