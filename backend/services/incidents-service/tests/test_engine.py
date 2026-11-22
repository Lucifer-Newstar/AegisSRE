from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from incidents_service.config import Settings
from incidents_service.engine import DomainError, ReliabilityLoop
from incidents_service.models import Decision, Event, now
from incidents_service.repository import Repository


@pytest.fixture
def loop() -> ReliabilityLoop:
    return ReliabilityLoop(Repository("sqlite:///:memory:"), Settings(dev_mode=True))


def sample(
    loop: ReliabilityLoop, key: str, value: float, seconds: float, **overrides: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": key,
        "source": "chaoslab",
        "type": "metric",
        "service": "catalog-service",
        "timestamp": now() + timedelta(seconds=seconds),
        "payload": {"name": "memory_bytes", "value": value, "unit": "bytes"},
    }
    body.update(overrides)
    return loop.ingest(Event.model_validate(body))


def open_incident(loop: ReliabilityLoop) -> str:
    for index in range(12):
        sample(loop, f"warm-{index}", 100.0, -30 + index)
    loop.ingest(
        Event(
            id="log-1",
            source="loki",
            type="log",
            service="catalog-service",
            timestamp=now() - timedelta(seconds=2),
            payload={"level": "ERROR", "message": "Out of memory: OOMKilled"},
        )
    )
    result = sample(loop, "fault-1", 900.0, -1)
    assert result["anomalous"]
    return str(result["incident_id"])


def test_baseline_incident_correlation_and_persistence(loop: ReliabilityLoop) -> None:
    incident_id = open_incident(loop)
    with loop.repo.transaction() as tx:
        incident = tx.incident(incident_id)
        assert incident is not None
        assert incident.status == "investigating"
        assert incident.plan.action == "restart"
        assert incident.analysis.hypotheses[0]["cause"] == "memory_exhaustion"
        assert "log-1" in incident.analysis.evidence_ids
        pending = [event for _, event in tx.pending()]
        assert len(pending) == 4
        anomaly = next(event for event in pending if event["type"] == "anomaly")
        first_sample = tx.event("warm-0")
        assert first_sample is not None
        assert datetime.fromisoformat(
            anomaly["payload"]["window"]["start"]
        ) == datetime.fromisoformat(first_sample["timestamp"])
        audit_events = [event for event in pending if event["type"] == "audit"]
        assert len(audit_events) == 2
        assert all(event["service"] == "catalog-service" for event in audit_events)
        assert all(event["payload"]["target"] == incident_id for event in audit_events)
        assert len(tx.audits(incident_id)) == 2
    sample(loop, "fault-2", 800.0, 0)
    with loop.repo.transaction() as tx:
        assert len(tx.list_incidents()) == 1
        assert (
            len(
                tx.baseline(
                    Event(
                        id="x",
                        source="chaoslab",
                        type="metric",
                        service="catalog-service",
                        payload={"name": "memory_bytes", "value": 1, "unit": "bytes"},
                    ).series()
                )
            )
            == 12
        )


def test_duplicate_content_and_out_of_order(loop: ReliabilityLoop) -> None:
    event = Event(
        id="stable",
        source="prometheus",
        type="metric",
        service="catalog-service",
        payload={"name": "latency", "value": 1},
    )
    assert not loop.ingest(event)["duplicate"]
    assert loop.ingest(event)["duplicate"]
    changed = event.model_copy(deep=True)
    changed.payload["value"] = 2
    with pytest.raises(DomainError, match="different content"):
        loop.ingest(changed)
    older = event.model_copy(
        update={"id": "older", "timestamp": event.timestamp - timedelta(seconds=1)}
    )
    with pytest.raises(DomainError, match="increasing"):
        loop.ingest(older)
    with loop.repo.transaction() as tx:
        assert tx.event("older") is None


def test_approval_execution_recovery_requires_fresh_all_checks(
    loop: ReliabilityLoop, monkeypatch: pytest.MonkeyPatch
) -> None:
    incident_id = open_incident(loop)
    denied = loop.execute(incident_id, "tester")
    assert denied.execution_output is not None and denied.execution_output.startswith("DENIED")
    with loop.repo.transaction() as tx:
        assert any(a["action"] == "remediation.denied" for a in tx.audits())
    loop.decide(incident_id, "approved", Decision(actor="navin", note="demo workload only"))
    executed = loop.execute(incident_id, "navin")
    assert executed.status == "verifying" and executed.executed_at
    assert executed.execution_output and "SIMULATION ONLY" in executed.execution_output
    verification_clock = now() + timedelta(seconds=4)
    monkeypatch.setattr("incidents_service.engine.now", lambda: verification_clock)
    for index in range(3):
        sample(loop, f"healthy-{index}", 100, index + 1)
    with loop.repo.transaction() as tx:
        item = tx.incident(incident_id)
        assert item is not None and item.status == "verifying"  # metrics alone are insufficient
    healthy_time = now() + timedelta(seconds=5)
    monkeypatch.setattr("incidents_service.engine.now", lambda: healthy_time)
    body = {"status": "healthy", "slo_ok": True, "errors_ok": True, "latency_ok": False}
    loop.ingest(
        Event(
            id="bad-health",
            source="registry",
            type="health",
            service="catalog-service",
            timestamp=healthy_time,
            payload=body,
        )
    )
    with loop.repo.transaction() as tx:
        item = tx.incident(incident_id)
        assert item and item.status == "verifying"
    body["latency_ok"] = True
    loop.ingest(
        Event(
            id="good-health",
            source="registry",
            type="health",
            service="catalog-service",
            timestamp=healthy_time + timedelta(microseconds=1),
            payload=body,
        )
    )
    monkeypatch.setattr("incidents_service.engine.now", lambda: healthy_time + timedelta(seconds=1))
    loop.ingest(
        Event(
            id="good-health-2",
            source="registry",
            type="health",
            service="catalog-service",
            timestamp=healthy_time + timedelta(microseconds=2),
            payload=body,
        )
    )
    report = loop.postmortem(incident_id)
    assert report["simulation"] is True and report["incident"]["status"] == "closed"


def test_rejection_and_bad_transitions(loop: ReliabilityLoop) -> None:
    key = open_incident(loop)
    item = loop.decide(key, "rejected", Decision(actor="navin", note="unsafe"))
    assert item.status == "escalated"
    denied = loop.execute(key, "navin")
    assert denied.execution_output and denied.execution_output.startswith("DENIED")
    with pytest.raises(DomainError):
        loop.decide(key, "approved", Decision(actor="navin"))
    with pytest.raises(DomainError):
        loop.postmortem(key)


def test_kill_switch_blocks_even_approved_action(loop: ReliabilityLoop) -> None:
    key = open_incident(loop)
    loop.decide(key, "approved", Decision(actor="navin"))
    loop.set_mode("observe", "navin")
    denied = loop.execute(key, "navin")
    assert denied.execution_output and "Kill switch" in denied.execution_output
    with loop.repo.transaction() as tx:
        assert not tx.get_state("executions", [])


def test_execution_error_is_not_blindly_retried(
    loop: ReliabilityLoop, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = open_incident(loop)
    loop.decide(key, "approved", Decision(actor="navin"))
    calls: list[int] = []

    def fail(*args: Any) -> Any:
        calls.append(1)
        raise TimeoutError("unknown external effect")

    monkeypatch.setattr(loop.executor, "run", fail)
    assert loop.execute(key, "navin").status == "escalated"
    assert loop.execute(key, "navin").status == "escalated"
    assert calls == [1]


def test_unrecovered_is_escalated_at_deadline(
    loop: ReliabilityLoop, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = open_incident(loop)
    loop.decide(key, "approved", Decision(actor="navin"))
    item = loop.execute(key, "navin")
    assert item.verification_deadline
    monkeypatch.setattr(
        "incidents_service.engine.now", lambda: item.verification_deadline + timedelta(seconds=1)
    )
    loop.sweep()
    with loop.repo.transaction() as tx:
        stored = tx.incident(key)
        assert stored and stored.status == "escalated"


def test_environment_isolation(loop: ReliabilityLoop) -> None:
    open_incident(loop)
    result = sample(loop, "prod-sample", 900, 0, environment="prod")
    assert result["baseline_ready"] is False and result["incident_id"] is None
