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
        executor.run(
            Plan(action="config_update", target="catalog-service", risk="high", reason="bad")
        )


def test_real_executor_passes_exact_argv_not_a_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(api_token="test", executor="kubernetes", kube_context="kind-aegissre")
    calls: list[list[str]] = []
    obj = {
        "metadata": {
            "namespace": "aegissre-demo",
            "uid": "uid-1",
            "labels": {"aegissre.managed": "true"},
            "annotations": {"deployment.kubernetes.io/revision": "4"},
        },
        "spec": {"replicas": 2},
    }

    def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        assert kwargs.get("shell", False) is False
        return subprocess.CompletedProcess(
            args, 0, json.dumps(obj) if "get" in args else "restarted"
        )

    monkeypatch.setattr(subprocess, "run", run)
    result = Executor(settings).run(plan())
    assert result.undo["uid"] == "uid-1"
    assert calls[-1] == [
        "kubectl",
        "--context",
        "kind-aegissre",
        "--namespace",
        "aegissre-demo",
        "rollout",
        "restart",
        "deployment/catalog-service",
    ]


def test_rollback_requires_numeric_recent_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    executor = Executor(
        Settings(api_token="test", executor="kubernetes", kube_context="kind-aegissre")
    )
    obj = {
        "metadata": {
            "namespace": "aegissre-demo",
            "labels": {"aegissre.managed": "true"},
            "annotations": {"deployment.kubernetes.io/revision": "4"},
        },
        "spec": {"replicas": 2},
    }
    monkeypatch.setattr(executor, "_kubectl", lambda args: json.dumps(obj))
    with pytest.raises(ExecutionError, match="numeric"):
        executor.run(
            Plan(
                action="rollback",
                target="catalog-service",
                reason="bad",
                risk="high",
                revision="gitsha",
            )
        )
    with pytest.raises(ExecutionError, match="distance"):
        executor.run(
            Plan(
                action="rollback", target="catalog-service", reason="bad", risk="high", revision="1"
            )
        )


def test_rollback_restores_only_uniquely_owned_template_with_compare_and_swap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = Executor(Settings(api_token="test", executor="kubernetes", kube_context="kind-test"))
    current = {
        "metadata": {
            "namespace": "aegissre-demo",
            "uid": "owned",
            "resourceVersion": "42",
            "labels": {"aegissre.managed": "true"},
            "annotations": {"deployment.kubernetes.io/revision": "4"},
        },
        "spec": {"replicas": 1},
    }
    rs: dict[str, Any] = {
        "metadata": {
            "namespace": "aegissre-demo",
            "annotations": {"deployment.kubernetes.io/revision": "3"},
            "ownerReferences": [{"uid": "owned", "kind": "Deployment", "controller": True}],
        },
        "spec": {
            "template": {
                "metadata": {
                    "labels": {"app": "catalog-service", "pod-template-hash": "generated"}
                },
                "spec": {
                    "containers": [{"name": "catalog-service", "image": "known-retained-image"}]
                },
            }
        },
    }
    calls: list[list[str]] = []

    def kubectl(args: list[str]) -> str:
        calls.append(args)
        return (
            json.dumps({"items": [rs]})
            if args[:2] == ["get", "replicasets"]
            else json.dumps(current)
        )

    monkeypatch.setattr(executor, "_kubectl", kubectl)
    rollback = Plan(
        action="rollback", target="catalog-service", reason="test", risk="high", revision="3"
    )
    executor.run(rollback)
    patch = json.loads(calls[-1][-1])
    assert calls[-1][:4] == ["patch", "deployment/catalog-service", "--type=json", "-p"]
    assert patch[0] == {"op": "test", "path": "/metadata/uid", "value": "owned"}
    assert patch[1]["value"] == "42"
    assert "pod-template-hash" not in patch[2]["value"]["metadata"]["labels"]
    rs["metadata"]["ownerReferences"][0]["uid"] = "another-deployment"
    with pytest.raises(ExecutionError, match="uniquely owned"):
        executor.run(rollback)


def test_live_rollback_preflight_rejects_config_changes_and_changed_current_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = Executor(Settings(api_token="test", executor="kubernetes", kube_context="kind-test"))
    template: dict[str, Any] = {
        "metadata": {"labels": {"app": "catalog-service"}},
        "spec": {"containers": [{"name": "catalog-service", "image": "new"}]},
    }
    obj: dict[str, Any] = {
        "metadata": {
            "namespace": "aegissre-demo",
            "uid": "owned",
            "resourceVersion": "42",
            "generation": 1,
            "labels": {"aegissre.managed": "true"},
            "annotations": {"deployment.kubernetes.io/revision": "4"},
        },
        "spec": {"replicas": 1, "template": template},
        "status": {"observedGeneration": 1},
    }
    prior = json.loads(json.dumps(template))
    prior["spec"]["containers"][0]["image"] = "prior"
    monkeypatch.setattr(executor, "_kubectl", lambda args: json.dumps(obj))
    monkeypatch.setattr(executor, "_rollback_template", lambda *_: prior)
    rollback = Plan(
        action="rollback", target="catalog-service", revision="3", risk="low", reason="unit"
    )
    context = executor.policy_context(rollback)
    assert context["rollback_distance"] == 1 and context["live_revision"] == "4"
    with pytest.raises(ExecutionError, match="revision changed"):
        executor.run(
            rollback,
            automatic=True,
            expected_uid="owned",
            expected_revision="5",
            expected_current_template_digest=context["current_template_digest"],
            expected_template_digest=context["target_template_digest"],
            dispatch_allowed=lambda: True,
        )
    prior["spec"]["containers"][0]["env"] = [{"name": "MIGRATION", "value": "unsafe"}]
    with pytest.raises(ExecutionError, match="image-only"):
        executor.policy_context(rollback)


def test_structured_kubectl_reads_are_complete_or_explicitly_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = Executor(Settings(api_token="test", executor="kubernetes", kube_context="kind-test"))
    payload = json.dumps({"items": [], "padding": "x" * 40000})

    def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, payload)

    monkeypatch.setattr(subprocess, "run", run)
    assert json.loads(executor._kubectl(["get", "replicasets", "-o", "json"])) == json.loads(
        payload
    )
    payload = "x" * 4_000_001
    with pytest.raises(ExecutionError, match="structured-read limit"):
        executor._kubectl(["get", "replicasets", "-o", "json"])
