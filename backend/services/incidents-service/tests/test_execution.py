from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest
from incidents_service.config import Settings
from incidents_service.execution import ExecutionError, Executor
from incidents_service.models import Plan


def plan(**values: Any) -> Plan:
    return Plan(action="restart", target="catalog-service", reason="crash", risk="medium", **values)


def test_simulation_never_calls_a_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("must not launch a subprocess")
    monkeypatch.setattr(subprocess, "run", forbidden)
    result = Executor(Settings(dev_mode=True)).run(plan())
    assert "SIMULATION ONLY" in result.output


def test_target_and_action_are_allowlisted() -> None:
    executor = Executor(Settings(dev_mode=True))
    with pytest.raises(ExecutionError):
        executor.run(Plan(action="restart", target="postgres", risk="medium", reason="bad"))
    with pytest.raises(ExecutionError):
        executor.run(Plan(action="config_update", target="catalog-service", risk="high", reason="bad"))


def test_real_executor_passes_exact_argv_not_a_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(api_token="test", executor="kubernetes", kube_context="kind-aegissre")
    calls: list[list[str]] = []
    obj = {"metadata": {"namespace": "aegissre-demo", "uid": "uid-1", "labels": {"aegissre.managed": "true"},
                        "annotations": {"deployment.kubernetes.io/revision": "4"}}, "spec": {"replicas": 2}}

    def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        assert kwargs.get("shell", False) is False
        return subprocess.CompletedProcess(args, 0, json.dumps(obj) if "get" in args else "restarted")

    monkeypatch.setattr(subprocess, "run", run)
    result = Executor(settings).run(plan())
    assert result.undo["uid"] == "uid-1"
    assert calls[-1] == ["kubectl", "--context", "kind-aegissre", "--namespace", "aegissre-demo", "rollout", "restart", "deployment/catalog-service"]


def test_rollback_requires_numeric_recent_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    executor = Executor(Settings(api_token="test", executor="kubernetes", kube_context="kind-aegissre"))
    obj = {"metadata": {"namespace": "aegissre-demo", "labels": {"aegissre.managed": "true"},
                        "annotations": {"deployment.kubernetes.io/revision": "4"}}, "spec": {"replicas": 2}}
    monkeypatch.setattr(executor, "_kubectl", lambda args: json.dumps(obj))
    with pytest.raises(ExecutionError, match="numeric"):
        executor.run(Plan(action="rollback", target="catalog-service", reason="bad", risk="high", revision="gitsha"))
    with pytest.raises(ExecutionError, match="distance"):
        executor.run(Plan(action="rollback", target="catalog-service", reason="bad", risk="high", revision="1"))
