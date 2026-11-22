"""Scheduler/engine tests use explicit fixture context, never live acceptance claims."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from incidents_service.config import Settings
from incidents_service.engine import ReliabilityLoop
from incidents_service.execution import ExecutionError, Executor
from incidents_service.models import Analysis, Incident, Plan, now
from incidents_service.policy import Policy, Rule
from incidents_service.repository import Repository


def configured() -> tuple[ReliabilityLoop, str]:
    loop = ReliabilityLoop(Repository("sqlite:///:memory:"), Settings(dev_mode=True))
    loop.policy = Policy(
        rules={"scale": Rule(risk="low", requires_approval=False, auto=True, reversible=True)}
    )
    item = Incident(
        id="auto-one",
        service="catalog-service",
        environment="dev",
        title="cpu",
        status="investigating",
        signals=[],
        evidence_ids=[],
        audit=[],
        analysis=Analysis(summary="cpu", confidence="low", evidence_ids=[]),
        plan=Plan(
            action="scale",
            target="catalog-service",
            replicas=3,
            reason="bounded test",
            risk="low",
            reversible=True,
        ),
    )
    with loop.repo.transaction() as tx:
        tx.save_incident(item)
    loop.set_mode("auto-safe", "test-operator")
    return loop, item.id


def test_scheduler_runs_once_and_records_automatic_actor(monkeypatch: pytest.MonkeyPatch) -> None:
    loop, key = configured()
    monkeypatch.setattr(loop.executor, "policy_context", lambda _: {"current_replicas": 2})
    assert loop.run_automatic() == 1
    assert loop.run_automatic() == 0
    with loop.repo.transaction() as tx:
        item = tx.incident(key)
        assert item and item.status == "verifying"
        assert item.execution_output and "SIMULATION ONLY" in item.execution_output
        assert any(
            a.actor == "policy:auto" and a.action == "remediation.started" for a in item.audit
        )


@pytest.mark.parametrize(
    "case",
    [
        "recommend",
        "observe",
        "approved",
        "deferred",
        "stale",
        "missing-context",
        "wrong-replicas",
        "high-risk",
        "cooldown",
    ],
)
def test_scheduler_fails_closed(case: str, monkeypatch: pytest.MonkeyPatch) -> None:
    loop, key = configured()
    monkeypatch.setattr(loop.executor, "policy_context", lambda _: {"current_replicas": 2})
    if case in {"recommend", "observe"}:
        loop.set_mode("recommend" if case == "recommend" else "observe", "test-operator")
    with loop.repo.transaction() as tx:
        item = tx.incident(key)
        assert item
        if case in {"approved", "deferred"}:
            item.approval = "approved" if case == "approved" else "deferred"
        if case == "stale":
            item.updated_at = now() - timedelta(seconds=61)
        if case == "high-risk":
            item.plan.risk = "high"
        if case == "wrong-replicas":
            item.plan.replicas = 4
        if case == "cooldown":
            tx.put_state(
                "executions",
                [{"at": now().isoformat(), "target": item.service, "incident_id": "previous"}],
            )
        tx.save_incident(item)
    if case == "missing-context":
        monkeypatch.setattr(loop.executor, "policy_context", lambda _: {})
    monkeypatch.setattr(loop.executor, "run", lambda _: pytest.fail("unsafe dispatch"))
    assert loop.run_automatic() == 0


def test_context_read_failure_never_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    loop, _ = configured()

    def fail(_: Plan) -> dict[str, int]:
        raise ExecutionError("unavailable")

    monkeypatch.setattr(loop.executor, "policy_context", fail)
    monkeypatch.setattr(loop.executor, "run", lambda _: pytest.fail("unsafe dispatch"))
    assert loop.run_automatic() == 0


def test_live_context_is_read_from_managed_observed_object(monkeypatch: pytest.MonkeyPatch) -> None:
    loop, key = configured()
    executor = Executor(Settings(api_token="test", executor="kubernetes", kube_context="owned"))
    with loop.repo.transaction() as tx:
        item = tx.incident(key)
        assert item
    obj: dict[str, Any] = {
        "metadata": {
            "namespace": "aegissre-demo",
            "uid": "actual",
            "generation": 4,
            "labels": {"aegissre.managed": "true"},
        },
        "spec": {"replicas": 2},
        "status": {"observedGeneration": 4},
    }
    monkeypatch.setattr(executor, "_kubectl", lambda _: json.dumps(obj))
    assert executor.policy_context(item.plan) == {"current_replicas": 2, "target_uid": "actual"}
    obj["status"]["observedGeneration"] = 3
    with pytest.raises(ExecutionError):
        executor.policy_context(item.plan)


def test_runtime_dispatches_only_with_successful_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import fakeredis
    from eventbus import EventBus
    from incidents_service.runtime import Runtime

    loop, _ = configured()
    monkeypatch.setattr(loop.executor, "policy_context", lambda _: {"current_replicas": 2})
    monkeypatch.setattr(
        "eventbus.eventbus.Redis.from_url",
        lambda *a, **k: fakeredis.FakeRedis(decode_responses=True),
    )
    runtime = Runtime(loop, bus=EventBus("redis://unused"))
    runtime.collector_failures = {"tempo:catalog-service": "HTTPStatusError"}
    runtime.tick()
    assert runtime.last_counts["automatic_actions"] == 0
    runtime.collector_failures = {}
    runtime.tick()
    assert runtime.last_counts["automatic_actions"] == 1
    runtime.tick()
    assert runtime.last_counts["automatic_actions"] == 0
    runtime.close()


def test_executor_rechecks_scale_direction_at_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    loop, key = configured()
    with loop.repo.transaction() as tx:
        item = tx.incident(key)
        assert item
    executor = Executor(Settings(api_token="test", executor="kubernetes", kube_context="owned"))
    obj: dict[str, Any] = {
        "metadata": {
            "namespace": "aegissre-demo",
            "uid": "actual",
            "labels": {"aegissre.managed": "true"},
        },
        "spec": {"replicas": 4},
    }
    calls: list[list[str]] = []

    def read(args: list[str]) -> str:
        calls.append(args)
        return json.dumps(obj)

    monkeypatch.setattr(executor, "_kubectl", read)
    with pytest.raises(ExecutionError):
        executor.run(item.plan, automatic=True, expected_uid="actual")
    assert len(calls) == 1 and calls[0][0] == "get"


def test_capacity_anomaly_plans_from_live_replicas_not_guessed_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from incidents_service.models import Event

    loop, key = configured()
    with loop.repo.transaction() as tx:
        seeded = tx.incident(key)
        assert seeded
        seeded.approval = "deferred"
        tx.save_incident(seeded)
    # Separate service so the explicitly seeded incident does not mask creation.
    monkeypatch.setattr(loop.executor, "policy_context", lambda _: {"current_replicas": 2})
    for index in range(13):
        result = loop.ingest(
            Event(
                id="cpu-" + str(index),
                source="prometheus",
                type="metric",
                service="cart-service",
                timestamp=now() - timedelta(seconds=20 - index),
                payload={
                    "name": "cpu_usage_percent",
                    "value": 100 if index == 12 else 5,
                    "unit": "percent_of_one_core",
                },
            )
        )
    with loop.repo.transaction() as tx:
        item = tx.incident(str(result["incident_id"]))
        assert item and item.plan.action == "scale" and item.plan.replicas is None
        assert item.plan.risk == "low" and item.plan.reversible
    assert loop.run_automatic() == 1


def test_capacity_anomaly_without_live_context_escalates() -> None:
    from incidents_service.models import Event

    loop, _ = configured()
    for index in range(13):
        result = loop.ingest(
            Event(
                id="cpu-missing-" + str(index),
                source="prometheus",
                type="metric",
                service="cart-service",
                timestamp=now() - timedelta(seconds=20 - index),
                payload={
                    "name": "cpu_usage_percent",
                    "value": 100 if index == 12 else 5,
                    "unit": "percent_of_one_core",
                },
            )
        )
    with loop.repo.transaction() as tx:
        item = tx.incident(str(result["incident_id"]))
        assert item and item.plan.action == "scale" and item.plan.replicas is None
    assert loop.run_automatic() == 0


def test_kill_switch_during_slow_preflight_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    loop, _ = configured()

    def preflight(_: Plan) -> dict[str, int]:
        loop.set_mode("observe", "operator-during-read")
        return {"current_replicas": 2}

    monkeypatch.setattr(loop.executor, "policy_context", preflight)
    monkeypatch.setattr(loop.executor, "run", lambda _: pytest.fail("Kill switch ignored"))
    assert loop.run_automatic() == 0


def test_live_plan_fill_cannot_refresh_a_stale_incident(monkeypatch: pytest.MonkeyPatch) -> None:
    loop, key = configured()
    with loop.repo.transaction() as tx:
        item = tx.incident(key)
        assert item
        item.plan.replicas = None
        item.updated_at = now() - timedelta(seconds=61)
        tx.save_incident(item)
    monkeypatch.setattr(loop.executor, "policy_context", lambda _: {"current_replicas": 2})
    assert loop.run_automatic() == 0
    with loop.repo.transaction() as tx:
        item = tx.incident(key)
        assert item and item.plan.replicas is None
