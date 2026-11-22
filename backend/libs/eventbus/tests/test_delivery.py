"""Delivery recovery, poison-message handling and actual time retention."""

from __future__ import annotations

from typing import Any

import fakeredis
import pytest
from eventbus import EventBus, stream_name
from telemetry import EventEnvelope


@pytest.fixture
def bus(monkeypatch: pytest.MonkeyPatch) -> EventBus:
    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("eventbus.eventbus.Redis.from_url", classmethod(lambda cls, *a, **k: fake))
    return EventBus("redis://localhost:6379/0", stream_ttls={"st:metric": 3600})


def envelope(key: str) -> EventEnvelope:
    return EventEnvelope(
        id=key,
        source="prometheus",
        type="metric",
        service="catalog-service",
        payload={"name": "latency", "value": 0.1},
    )


def test_crashed_consumer_pending_entries_can_be_reclaimed(bus: EventBus) -> None:
    bus.publish(envelope("one"))
    first = bus.read("metric", "detector", "crashed", block_ms=0)
    assert len(first) == 1 and bus.pending_count("metric", "detector") == 1
    cursor, recovered = bus.reclaim("metric", "detector", "replacement", min_idle_ms=0)
    assert isinstance(cursor, str)
    assert [(mid, event.id) for mid, event in recovered] == [(first[0][0], "one")]
    bus.ack("metric", "detector", recovered[0][0])
    assert bus.pending_count("metric", "detector") == 0


def test_retention_is_seconds_not_a_message_count(bus: EventBus) -> None:
    seconds, _ = bus._redis.time()
    bus._redis.xadd(
        "st:metric",
        {"envelope": envelope("old").model_dump_json()},
        id=f"{(seconds - 7200) * 1000}-0",
    )
    bus.publish(envelope("new"))
    assert bus.stream_length("metric") == 1
    assert bus.read("metric", "detector", "one", block_ms=0)[0][1].id == "new"


def test_malformed_message_requires_explicit_quarantine_and_does_not_hide_valid_peer(
    bus: EventBus,
) -> None:
    malformed = str(bus._redis.xadd("st:metric", {"envelope": "not valid JSON"}))
    bus.publish(envelope("valid"))
    invalid: list[tuple[str, str]] = []

    def quarantine(mid: str, reason: str) -> None:
        invalid.append((mid, reason))
        bus.quarantine("metric", "detector", mid, reason)

    rows = bus.read("metric", "detector", "one", block_ms=0, on_invalid=quarantine)
    assert len(rows) == 1 and rows[0][1].id == "valid"
    assert invalid[0][0] == malformed
    assert bus._redis.xlen("dlq:metric") == 1
    assert bus.pending_count("metric", "detector") == 1  # the good event is not acked prematurely
    bus.ack("metric", "detector", rows[0][0])
    assert bus.pending_count("metric", "detector") == 0


def test_default_parser_never_silently_acknowledges_invalid_messages(bus: EventBus) -> None:
    bus._redis.xadd("st:metric", {"envelope": "invalid"})
    with pytest.raises(ValueError, match="remains pending"):
        bus.read("metric", "detector", "one", block_ms=0)
    assert bus.pending_count("metric", "detector") == 1


def test_stream_and_batch_bounds_are_explicit(bus: EventBus) -> None:
    with pytest.raises(ValueError):
        stream_name("unknown")
    with pytest.raises(ValueError):
        bus.read("metric", "detector", "one", count=501)
    with pytest.raises(ValueError):
        bus.reclaim("metric", "detector", "one", min_idle_ms=-1)


def test_only_group_exists_errors_are_suppressed(
    bus: EventBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise ConnectionError("transport failed")

    monkeypatch.setattr(bus._redis, "xgroup_create", fail)
    with pytest.raises(ConnectionError):
        bus.ensure_group("metric", "detector")
