#!/usr/bin/env python3
"""Explicit policy fixture drives real worker + kubectl scale in the owned CI cluster.

Not a fault-detection experiment or a measured evaluation success-rate claim.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/ci"))
import kind_platform_gate as fixture  # type: ignore[import-not-found] # noqa: E402
from incidents_service.config import Settings  # noqa: E402
from incidents_service.engine import ReliabilityLoop  # noqa: E402
from incidents_service.models import Analysis, Incident, Plan  # noqa: E402
from incidents_service.policy import Policy, Rule  # noqa: E402
from incidents_service.repository import Repository  # noqa: E402


def main() -> None:
    if not fixture.owned():
        raise RuntimeError("Refusing an unowned cluster")
    base = fixture.directory()
    os.environ["PATH"] = str(base / "bin") + os.pathsep + os.environ["PATH"]
    os.environ["KUBECONFIG"] = str(base / "kubeconfig")
    target = "catalog-service"

    def deployment() -> dict[str, Any]:
        return cast(
            dict[str, Any],
            json.loads(
                fixture.kubectl(
                    "get", "deployment", target, "-n", fixture.NS, "-o", "json", capture=True
                )
            ),
        )

    original = deployment()
    count = original["spec"]["replicas"]
    if not 1 <= count < 10:
        raise RuntimeError("Fixture replicas outside bounded automatic-scale range")
    label = original["metadata"].get("labels", {}).get("aegissre.managed")
    loop = ReliabilityLoop(
        Repository("sqlite:///" + str(base / "autonomy-proof.db")),
        Settings(
            api_token="disposable-proof", executor="kubernetes", kube_context="kind-" + fixture.NAME
        ),
    )
    loop.policy = Policy(
        rules={"scale": Rule(risk="low", auto=True, requires_approval=False, reversible=True)}
    )
    item = Incident(
        id="owned-auto-scale",
        service=target,
        environment="dev",
        title="Explicit scale fixture",
        status="investigating",
        signals=[],
        evidence_ids=[],
        audit=[],
        analysis=Analysis(
            summary="Seeded fixture, not inferred diagnosis", confidence="low", evidence_ids=[]
        ),
        plan=Plan(
            action="scale",
            target=target,
            reason="Explicit owned-cluster test",
            risk="low",
            replicas=count + 1,
            reversible=True,
        ),
    )
    try:
        fixture.kubectl(
            "label", "deployment", target, "-n", fixture.NS, "aegissre.managed=true", "--overwrite"
        )
        with loop.repo.transaction() as tx:
            tx.save_incident(item)
        loop.set_mode("recommend", "fixture")
        assert loop.run_automatic() == 0 and deployment()["spec"]["replicas"] == count
        loop.set_mode("observe", "fixture")
        assert loop.run_automatic() == 0 and deployment()["spec"]["replicas"] == count
        loop.set_mode("auto-safe", "fixture")
        assert loop.run_automatic() == 1
        changed = deployment()
        assert changed["metadata"]["uid"] == original["metadata"]["uid"]
        assert changed["spec"]["replicas"] == count + 1
        assert loop.run_automatic() == 0
        loop.set_mode("observe", "fixture")
        assert loop.run_automatic() == 0
        with loop.repo.transaction() as tx:
            actual = tx.incident(item.id)
            assert actual and actual.status == "verifying" and actual.undo
            assert actual.undo["replicas"] == count
            assert any(
                a.action == "remediation.started" and a.actor == "policy:auto" for a in actual.audit
            )
        proof = {
            "fixture_seeded_plan": True,
            "real_kubernetes_executor": True,
            "uid": changed["metadata"]["uid"],
            "before": count,
            "after": count + 1,
            "incident": actual.model_dump(mode="json"),
            "not_evaluation_accuracy": True,
        }
    finally:
        loop.set_mode("observe", "fixture-cleanup")
        fixture.kubectl(
            "scale", "deployment/" + target, "-n", fixture.NS, "--replicas=" + str(count)
        )
        fixture.kubectl(
            "label",
            "deployment",
            target,
            "-n",
            fixture.NS,
            "aegissre.managed=" + label if label is not None else "aegissre.managed-",
            "--overwrite",
        )
        fixture.kubectl(
            "rollout", "status", "deployment/" + target, "-n", fixture.NS, "--timeout=120s"
        )
    assert deployment()["spec"]["replicas"] == count
    proof["restored_replicas"] = count
    (base / "diagnostics" / "autonomy-proof.json").write_text(json.dumps(proof, indent=2))
    print(
        "Real policy worker scale observed once; recommend/observe blocked; replicas restored. Seeded fixture, not acceptance accuracy."
    )


if __name__ == "__main__":
    main()
