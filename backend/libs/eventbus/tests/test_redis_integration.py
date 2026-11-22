"""Runs only against the fresh, isolated Redis service created by CI."""

from __future__ import annotations

import os
import time
import uuid
from urllib.parse import urlsplit

import pytest
from eventbus import EventBus
from telemetry import EventEnvelope

REDIS_URL = os.getenv("AEGIS_TEST_REDIS_URL", "")
pytestmark = pytest.mark.skipif(not REDIS_URL, reason="AEGIS_TEST_REDIS_URL not configured")


def test_actual_redis_crash_recovery_quarantine_and_time_retention() -> None:
    parsed = urlsplit(REDIS_URL)
    assert parsed.hostname in {"127.0.0.1", "localhost"} and parsed.path == "/15", (
        "Use a fresh local test server, database 15"
    )
    bus = EventBus(REDIS_URL, stream_ttls={"st:metric": 1})
    try:
        assert bus._redis.dbsize() == 0, (
            "Refusing to run against a database containing pre-existing data"
        )
        event = EventEnvelope(
            id=uuid.uuid4().hex,
            source="prometheus",
            type="metric",
            service="catalog-service",
            payload={"name": "latency", "value": 0.1},
        )
        group = f"test-{uuid.uuid4().hex}"
        bus.publish(event)
        initial = bus.read("metric", group, "crashed", block_ms=0)
        assert len(initial) == 1
        _, recovered = bus.reclaim("metric", group, "replacement", min_idle_ms=0)
        assert recovered[0][1].id == event.id
        bus.ack("metric", group, recovered[0][0])
        assert bus.pending_count("metric", group) == 0
        bus._redis.xadd("st:metric", {"envelope": "invalid JSON"})

        def quarantine(mid: str, reason: str) -> None:
            bus.quarantine("metric", group, mid, reason)

        assert bus.read("metric", group, "replacement", block_ms=0, on_invalid=quarantine) == []
        assert bus._redis.xlen("dlq:metric") == 1
        assert bus.pending_count("metric", group) == 0
        time.sleep(1.2)
        bus.publish(event.model_copy(update={"id": uuid.uuid4().hex}))
        assert bus.stream_length("metric") == 1
        time.sleep(1.2)
        bus.trim_all()
        assert bus.stream_length("metric") == 0
        assert bus.ping()
    finally:
        bus.close()
