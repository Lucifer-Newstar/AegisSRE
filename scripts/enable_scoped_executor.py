#!/usr/bin/env python3
"""Opt-in scoped executor identity for a newly owned local/CI evaluation fixture.

Enables the Kubernetes backend but keeps durable autonomy in observe mode.
No existing incident is approved/executed and no automatic policy is relaxed.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts/ci"))
import kind_platform_gate as fixture  # type: ignore[import-not-found] # noqa: E402


def enable() -> None:
    if not fixture.owned():
        raise RuntimeError("Refusing an unowned cluster")
    os.environ.update(fixture.FIXTURE)
    sys.path.insert(0, str(ROOT / "scripts"))
    from scripts.check_gateway_stack import request
    from scripts.check_runtime_stack import wait_for

    forwards = fixture.Forwards()
    try:
        forwards.start("api-gateway", 8080, 8000)
        wait_for(lambda: request("/api/v1/autonomy")["mode"] in {"observe", "recommend", "auto-safe"}, "gateway health")
        request("/api/v1/autonomy", body={"mode": "observe", "actor": "fixture"})
        for name in ("executor-account.yaml", "executor-role.yaml", "executor-binding.yaml", "executor-evidence-binding.yaml"):
            fixture.kubectl("apply", "-f", str(ROOT / "infra/evaluation" / name))
        document = {"apiVersion": "v1", "kind": "ConfigMap",
                    "metadata": {"name": "aegis-executor-kubeconfig", "namespace": fixture.NS},
                    "data": {"kubeconfig": (ROOT / "infra/evaluation/kubeconfig.yaml").read_text()}}
        fixture.kubectl("apply", "-f", "-", body=json.dumps(document))
        fixture.kubectl("patch", "deployment/incidents-service", "-n", fixture.NS,
                        "--type=strategic", "--patch-file", str(ROOT / "infra/evaluation/executor-patch.json"))
        fixture.kubectl("rollout", "status", "deployment/incidents-service", "-n", fixture.NS,
                        "--timeout=180s", timeout=200)
        wait_for(lambda: request("/api/v1/ready")["status"] == "ready", "scoped runtime ready", 120)
        def configured() -> bool:
            # Restart can leave one stale gateway upstream connection after
            # ready has succeeded. Retry reads only, never replay a write.
            state = request("/api/v1/autonomy")
            return bool(state["mode"] == "observe" and state["executor"] == "kubernetes")

        wait_for(configured, "deployed executor and durable observe mode", 120)
    finally:
        forwards.close()


if __name__ == "__main__":
    enable()
