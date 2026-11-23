from __future__ import annotations

import json
from typing import Any

import pytest
from incidents_service.config import Settings
from incidents_service.engine import DomainError
from incidents_service.execution import ExecutionError, Executor
from incidents_service.models import Decision
from test_autonomous_worker import configured


def test_cancel_before_dispatch_blocks_automatic_action(monkeypatch: pytest.MonkeyPatch) -> None:
    loop, key = configured()
    loop.cancel(key, Decision(actor="operator", note="stop"))
    monkeypatch.setattr(loop.executor, "run", lambda *a, **k: pytest.fail("Cancelled action ran"))
    assert loop.run_automatic() == 0
    with loop.repo.transaction() as tx:
        item = tx.incident(key)
        assert item and item.status == "escalated"
        assert item.audit[-1].action == "remediation.cancel_requested"


def test_cancellation_during_dispatch_retains_result_but_cannot_close(monkeypatch: pytest.MonkeyPatch) -> None:
    from incidents_service.execution import ExecutionResult
    loop, key = configured()
    monkeypatch.setattr(loop.executor, "policy_context", lambda _: {"current_replicas": 2})
    def run(*args: Any, **kwargs: Any) -> ExecutionResult:
        loop.cancel(key, Decision(actor="operator", note="in flight"))
        assert not kwargs["dispatch_allowed"]()
        return ExecutionResult("uncertain accepted command", {"executor":"simulation", "action":"scale"})
    monkeypatch.setattr(loop.executor, "run", run)
    loop.run_automatic()
    with loop.repo.transaction() as tx:
        item = tx.incident(key)
        assert item and item.status == "escalated" and item.undo
        assert any(a.action == "remediation.cancel_reconcile" for a in item.audit)


def test_scale_undo_reserved_once_and_keeps_incident_escalated() -> None:
    loop, key = configured()
    with loop.repo.transaction() as tx:
        item = tx.incident(key)
        assert item
        item.status = "verifying"
        item.undo = {"executor":"simulation", "action":"scale"}
        tx.save_incident(item)
    actual = loop.undo_scale(key, Decision(actor="operator", note="undo"))
    assert actual.status == "escalated" and actual.resolved_at is None
    with pytest.raises(DomainError, match="already reserved"):
        loop.undo_scale(key, Decision(actor="operator"))


def test_real_scale_undo_is_identity_template_and_resource_version_guarded(monkeypatch: pytest.MonkeyPatch) -> None:
    executor = Executor(Settings(api_token="test", executor="kubernetes", kube_context="owned"))
    obj: dict[str, Any] = {"metadata":{"uid":"owned", "resourceVersion":"42", "namespace":"aegissre-demo",
        "labels":{"aegissre.managed":"true"}}, "spec":{"replicas":3, "template":{"spec":{"containers":[]}}}}
    record = {"executor":"kubernetes", "target":"catalog-service", "uid":"owned", "action":"scale",
        "replicas":2, "applied_replicas":3, "template_digest":executor._template_digest(obj["spec"]["template"])}
    calls: list[list[str]] = []
    def kubectl(args: list[str]) -> str:
        calls.append(args)
        return json.dumps(obj) if args[0] == "get" else "patched"
    monkeypatch.setattr(executor, "_kubectl", kubectl)
    assert executor.undo(record) == "patched"
    patch = json.loads(calls[-1][-1])
    assert patch[0] == {"op":"test", "path":"/metadata/uid", "value":"owned"}
    assert patch[1]["value"] == "42" and patch[2]["value"] == 2
    obj["spec"]["replicas"] = 4
    with pytest.raises(ExecutionError, match="preconditions"):
        executor.undo(record)
    record["action"] = "rollback"
    with pytest.raises(ExecutionError, match="Only bounded scale"):
        executor.undo(record)
