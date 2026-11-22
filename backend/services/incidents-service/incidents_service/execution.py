"""Allowlisted, argv-only executors. No shell and no LLM-provided commands."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from incidents_service.config import Settings
from incidents_service.models import Plan


class ExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecutionResult:
    output: str
    undo: dict[str, Any]


class Executor:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _kubectl(self, args: list[str]) -> str:
        result = subprocess.run(
            [
                "kubectl",
                "--context",
                self.settings.kube_context,
                "--namespace",
                self.settings.kube_namespace,
                *args,
            ],
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        if result.returncode:
            # Do not leak kube credentials or verbose command output to clients.
            raise ExecutionError(
                f"kubectl returned {result.returncode}; inspect executor logs locally"
            )
        return result.stdout[:32000]

    def policy_context(self, plan: Plan) -> dict[str, Any]:
        """Read live scale preconditions. Simulation never invents a replica count.

        Rollback remains fail-closed until observed risk/rollout context is wired.
        The scale executor reads again and uses Kubernetes' replica precondition.
        """
        if self.settings.executor != "kubernetes" or plan.action != "scale":
            return {}
        if plan.target not in self.settings.allowed_targets:
            raise ExecutionError("Target not allowlisted")
        obj = json.loads(self._kubectl(["get", "deployment", plan.target, "-o", "json"]))
        meta, spec = obj.get("metadata", {}), obj.get("spec", {})
        if (
            meta.get("namespace") != self.settings.kube_namespace
            or meta.get("labels", {}).get("aegissre.managed") != "true"
            or not meta.get("uid")
            or spec.get("paused")
            or obj.get("status", {}).get("observedGeneration", 0) < meta.get("generation", 1)
        ):
            raise ExecutionError("Automatic scale requires an observed managed deployment")
        replicas = spec.get("replicas")
        if isinstance(replicas, bool) or not isinstance(replicas, int) or not 1 <= replicas < 10:
            raise ExecutionError("Automatic scale requires a known bounded replica count")
        return {"current_replicas": replicas, "target_uid": str(meta["uid"])}

    def run(
        self,
        plan: Plan,
        *,
        automatic: bool = False,
        expected_uid: str | None = None,
        dispatch_allowed: Callable[[], bool] | None = None,
    ) -> ExecutionResult:
        if plan.target not in self.settings.allowed_targets:
            raise ExecutionError("Target not allowlisted")
        if plan.action not in {"restart", "rollback", "scale"}:
            raise ExecutionError("Action has no scoped executor")
        if self.settings.executor == "simulation":
            return ExecutionResult(
                f"SIMULATION ONLY: {plan.action} on {plan.target}. No workload was changed.",
                {"executor": "simulation", "action": plan.action, "target": plan.target},
            )
        obj: dict[str, Any] = json.loads(
            self._kubectl(["get", "deployment", plan.target, "-o", "json"])
        )
        meta = obj.get("metadata", {})
        if (
            meta.get("namespace") != self.settings.kube_namespace
            or meta.get("labels", {}).get("aegissre.managed") != "true"
        ):
            raise ExecutionError(
                "Deployment is not labelled aegissre.managed=true in the configured namespace"
            )
        if automatic and (not expected_uid or meta.get("uid") != expected_uid):
            raise ExecutionError("Automatic target identity changed after preflight")
        if obj.get("spec", {}).get("paused"):
            raise ExecutionError("Paused deployment cannot be remediated")
        revision = str(meta.get("annotations", {}).get("deployment.kubernetes.io/revision", ""))
        replicas = int(obj.get("spec", {}).get("replicas", 1))
        undo = {
            "executor": "kubernetes",
            "target": plan.target,
            "revision": revision,
            "replicas": replicas,
            "uid": str(meta.get("uid", "")),
            "action": plan.action,
        }
        if plan.action == "rollback":
            if not plan.revision or not plan.revision.isdigit() or not revision.isdigit():
                raise ExecutionError(
                    "Kubernetes rollback requires numeric rollout revisions, not image tags or git SHAs"
                )
            if not 1 <= int(revision) - int(plan.revision) <= 2:
                raise ExecutionError("Rollback distance must be one or two revisions")
            args = [
                "rollout",
                "undo",
                f"deployment/{plan.target}",
                f"--to-revision={plan.revision}",
            ]
        elif plan.action == "scale":
            if (
                plan.replicas is None
                or not 1 <= plan.replicas <= 10
                or abs(plan.replicas - replicas) > 1
                or (automatic and plan.replicas != replicas + 1)
            ):
                raise ExecutionError("Scaling is limited to one replica per action, within 1..10")
            args = [
                "scale",
                f"deployment/{plan.target}",
                f"--current-replicas={replicas}",
                f"--replicas={plan.replicas}",
            ]
        else:
            if replicas < 2:
                raise ExecutionError("Real rolling restart requires at least two replicas")
            args = ["rollout", "restart", f"deployment/{plan.target}"]
        if automatic and (dispatch_allowed is None or not dispatch_allowed()):
            raise ExecutionError("Automatic dispatch blocked by the current kill switch")
        output = self._kubectl(args)
        return ExecutionResult(output.strip()[:2000], undo)

    def undo(self, record: dict[str, Any]) -> str:
        if record.get("executor") == "simulation":
            return "SIMULATION ONLY: cancellation recorded, no workload changed"
        target = str(record.get("target", ""))
        if self.settings.executor != "kubernetes" or target not in self.settings.allowed_targets:
            raise ExecutionError("Undo target or executor does not match configuration")
        obj = json.loads(self._kubectl(["get", "deployment", target, "-o", "json"]))
        if obj.get("metadata", {}).get("uid") != record.get("uid"):
            raise ExecutionError("Deployment identity changed; automatic undo is unsafe")
        if record.get("action") == "scale":
            replicas = int(record["replicas"])
            return self._kubectl(["scale", f"deployment/{target}", f"--replicas={replicas}"])
        revision = str(record.get("revision", ""))
        if not revision.isdigit():
            raise ExecutionError("Prior revision is not known")
        return self._kubectl(
            ["rollout", "undo", f"deployment/{target}", f"--to-revision={revision}"]
        )
