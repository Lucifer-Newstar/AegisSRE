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
