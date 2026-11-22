from __future__ import annotations

from datetime import timedelta
from typing import Any

import fakeredis
import pytest
from eventbus import EventBus
from incidents_service.config import Settings
from incidents_service.delivery import DeliveryWorker
from incidents_service.engine import ReliabilityLoop
from incidents_service.models import Event, now
from incidents_service.repository import Repository
from telemetry import EventEnvelope


@pytest.fixture
def worker(monkeypatch: pytest.MonkeyPatch) -> DeliveryWorker:
    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("eventbus.eventbus.Redis.from_url", lambda *a, **k: fake)
    loop = ReliabilityLoop(Repository("sqlite:///:memory:"), Settings(dev_mode=True))
    return DeliveryWorker(loop, EventBus("redis://localhost"), reclaim_idle_ms=0)


def metric(index: int, value: float = 100) -> EventEnvelope:
    return EventEnvelope(
        id=f"sample-{index}",
        source="prometheus",
        type="metric",
        service="catalog-service",
        timestamp=now() - timedelta(seconds=60 - index),
        payload={"name": "memory_bytes", "value": value, "unit": "bytes"},
    )


def test_durable_stage_consume_and_domain_outbox(worker: DeliveryWorker) -> None:
    events = [metric(i, 900 if i == 12 else 100) for i in range(13)]
    for event in events:
        worker.stage(event)
        worker.stage(event)
    with worker.loop.repo.transaction() as tx:
        assert len(tx.pending()) == 13
    result = worker.tick()
    assert result["consumed"] == 13
    with worker.loop.repo.transaction() as tx:
        assert len(tx.list_incidents()) == 1
        assert len(tx.audits()) == 2
        assert not tx.pending()
    assert worker.bus.stream_length("audit") == 2
    assert worker.bus.stream_length("anomaly") == 1
    assert worker.bus.stream_length("incident") == 1
    assert worker.bus.pending_count("metric", worker.group) == 0
    worker.stage(events[-1])
    changed = events[-1].model_copy(deep=True)
    changed.payload["value"] = 901
    from incidents_service.engine import DomainError

    with pytest.raises(DomainError, match="different content"):
        worker.stage(changed)
    with worker.loop.repo.transaction() as tx:
        assert not tx.pending()


def test_publish_failure_preserves_outbox(
    worker: DeliveryWorker, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker.stage(metric(0))

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise ConnectionError("network unavailable")

    monkeypatch.setattr(worker.bus, "publish", fail)
    with pytest.raises(ConnectionError):
        worker.dispatch()
    with worker.loop.repo.transaction() as tx:
        assert len(tx.pending()) == 1


@pytest.mark.parametrize("failure", [RuntimeError, ValueError])
def test_commit_failure_does_not_ack_and_replacement_recovers(
    worker: DeliveryWorker,
    monkeypatch: pytest.MonkeyPatch,
    failure: type[Exception],
) -> None:
    event = metric(0)
    worker.bus.publish(event)
    ingest = worker.loop.ingest

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise failure("database or detector unavailable")

    monkeypatch.setattr(worker.loop, "ingest", fail)
    with pytest.raises(failure):
        worker.consume()
    assert worker.bus.pending_count("metric", worker.group) == 1
    monkeypatch.setattr(worker.loop, "ingest", ingest)
    replacement = DeliveryWorker(worker.loop, worker.bus, reclaim_idle_ms=0)
    assert replacement.consume() == 1
    with worker.loop.repo.transaction() as tx:
        assert tx.event(event.id) is not None
    assert worker.bus.pending_count("metric", worker.group) == 0


def test_commit_then_ack_failure_is_idempotent(
    worker: DeliveryWorker, monkeypatch: pytest.MonkeyPatch
) -> None:
    event = metric(0)
    worker.bus.publish(event)
    ack = worker.bus.ack

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise ConnectionError("ack lost")

    monkeypatch.setattr(worker.bus, "ack", fail)
    with pytest.raises(ConnectionError):
        worker.consume()
    with worker.loop.repo.transaction() as tx:
        assert tx.event(event.id) is not None
    monkeypatch.setattr(worker.bus, "ack", ack)
    worker.consume()
    with worker.loop.repo.transaction() as tx:
        assert tx.baseline(Event.model_validate(event.model_dump(mode="json")).series()) == [100]
    assert worker.bus.pending_count("metric", worker.group) == 0


def test_poison_wrong_stream_conflict_and_order_are_quarantined(worker: DeliveryWorker) -> None:
    event = metric(1)
    worker.bus.publish(event)
    worker.consume()
    changed = event.model_copy(deep=True)
    changed.payload["value"] = 12
    worker.bus.publish(changed)
    worker.bus.publish(metric(0))
    worker.bus._redis.xadd("st:metric", {"envelope": "malformed"})
    wrong = event.model_copy(update={"id": "wrong", "type": "health"})
    worker.bus._redis.xadd("st:metric", {"envelope": wrong.model_dump_json()})
    worker.consume()
    assert worker.bus.pending_count("metric", worker.group) == 0
    assert worker.bus._redis.xlen("dlq:metric") == 4
    with worker.loop.repo.transaction() as tx:
        assert tx.event("sample-0") is None
        assert tx.event("wrong") is None


def test_publish_then_delete_failure_replays_same_ids(
    worker: DeliveryWorker, monkeypatch: pytest.MonkeyPatch
) -> None:
    from incidents_service.repository import Transaction

    event = metric(0)
    worker.stage(event)
    delivered = Transaction.delivered

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("crash after publish")

    monkeypatch.setattr(Transaction, "delivered", fail)
    with pytest.raises(RuntimeError):
        worker.dispatch()
    monkeypatch.setattr(Transaction, "delivered", delivered)
    worker.tick()
    assert worker.bus.stream_length("metric") == 2
    with worker.loop.repo.transaction() as tx:
        assert tx.baseline(Event.model_validate(event.model_dump(mode="json")).series()) == [100]
        assert not tx.pending()
