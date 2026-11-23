#!/usr/bin/env python3
"""Real policy-worker rollback. Seeded prerequisites, not DI-5 accuracy."""

from __future__ import annotations

# ruff: noqa: E402
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/ci"))

import kind_platform_gate as fixture  # noqa: E402
from incidents_service.config import Settings  # noqa: E402
from incidents_service.deployment_intelligence import Rollout
from incidents_service.engine import ReliabilityLoop
from incidents_service.models import (
    Analysis,
    Incident,
    Plan,  # noqa: E402
    now,
)
from incidents_service.policy import Policy, Rule
from incidents_service.repository import Repository


def main() -> None:
    if not fixture.owned():
        raise RuntimeError("Refusing unowned cluster")
    base = fixture.directory()
    os.environ["PATH"] = str(base / "bin") + os.pathsep + os.environ["PATH"]
    os.environ["KUBECONFIG"] = str(base / "kubeconfig")

    def deployment() -> dict:
        return json.loads(
            fixture.kubectl(
                "get", "deployment", "catalog-service", "-n", fixture.NS, "-o", "json", capture=True
            )
        )

    original = deployment()
    label = original["metadata"].get("labels", {}).get("aegissre.managed")
    revision = original["metadata"]["annotations"]["deployment.kubernetes.io/revision"]
    forwards = fixture.Forwards()

    def status() -> int:
        try:
            with urllib.request.urlopen("http://127.0.0.1:19105/products", timeout=5) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code

    def wait_status(expected: int) -> int:
        deadline = time.monotonic() + 30
        while True:
            try:
                actual = status()
                if actual == expected:
                    return actual
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise AssertionError("Expected independently observed HTTP status not reached")
            time.sleep(0.2)

    try:
        fixture.kubectl(
            "label",
            "deployment",
            "catalog-service",
            "-n",
            fixture.NS,
            "aegissre.managed=true",
            "--overwrite",
        )
        fixture.kubectl(
            "set",
            "image",
            "deployment/catalog-service",
            "catalog-service=aegisshop/catalog-service:ci-faulty",
            "-n",
            fixture.NS,
        )
        fixture.kubectl(
            "rollout", "status", "deployment/catalog-service", "-n", fixture.NS, "--timeout=120s"
        )
        forwards.start("catalog-service", 19105, 9001)
        assert wait_status(503) == 503
        forwards.close()
        current_revision = deployment()["metadata"]["annotations"][
            "deployment.kubernetes.io/revision"
        ]
        clock = now()
        loop = ReliabilityLoop(
            Repository("sqlite:///" + str(base / "rollback-policy-proof.db")),
            Settings(
                api_token="disposable", executor="kubernetes", kube_context="kind-" + fixture.NAME
            ),
        )
        loop.policy = Policy(
            rules={
                "rollback": Rule(risk="low", auto=True, requires_approval=False, reversible=True)
            }
        )
        prior = Rollout(
            id="fixture-prior",
            workload_uid=original["metadata"]["uid"],
            service="catalog-service",
            environment="dev",
            deployment_id="fixture-prior",
            identity_explicit=True,
            revision=revision,
            previous_revision=None,
            started_at=clock - timedelta(days=1),
            window_end=clock - timedelta(hours=23),
            anchor_source="producer_started_at",
            phase="succeeded",
            last_phase_at=clock - timedelta(days=1),
            outcome="healthy",
            assessed_at=clock - timedelta(hours=22),
            source_event_ids=["fixture-prior-source"],
        )
        bad = Rollout(
            id="fixture-bad",
            workload_uid=original["metadata"]["uid"],
            service="catalog-service",
            environment="dev",
            deployment_id="fixture-bad",
            identity_explicit=True,
            revision=current_revision,
            previous_revision=revision,
            started_at=clock - timedelta(seconds=180),
            window_end=clock,
            anchor_source="producer_started_at",
            phase="succeeded",
            last_phase_at=clock - timedelta(seconds=120),
            outcome="bad",
            flagged_at=clock,
            incident_id="fixture-rollback",
            source_event_ids=["fixture-bad-source"],
            observation_ids=["fixture-observation"],
        )
        incident = Incident(
            id="fixture-rollback",
            service="catalog-service",
            environment="dev",
            title="Explicit synthetic policy prerequisites, actual faulty image",
            status="investigating",
            signals=[],
            evidence_ids=[],
            audit=[],
            analysis=Analysis(
                summary="Seeded prerequisites, not actual diagnosis",
                confidence="low",
                evidence_ids=[],
            ),
            plan=Plan(
                action="rollback",
                target="catalog-service",
                revision=revision,
                risk="high",
                reason="Explicit fixture",
            ),
            change_correlation="fixture-bad-source",
        )
        with loop.repo.transaction() as tx:
            tx.save_rollout(prior.model_dump(mode="json"))
            tx.save_rollout(bad.model_dump(mode="json"))
            tx.save_incident(incident)
            tx.put_state(
                "risk:fixture-prior",
                {
                    "status": "scored",
                    "probability": 0.2,
                    "deployment_started_at": prior.started_at.isoformat(),
                },
            )
        loop.set_mode("observe", "fixture")
        assert loop.run_automatic() == 0
        loop.set_mode("recommend", "fixture")
        assert loop.run_automatic() == 0
        loop.set_mode("auto-safe", "fixture")
        assert loop.run_automatic() == 1
        with loop.repo.transaction() as tx:
            actual = tx.incident(incident.id)
            assert actual and actual.status == "verifying" and actual.undo
        loop.set_mode("observe", "fixture")
        fixture.kubectl(
            "rollout", "status", "deployment/catalog-service", "-n", fixture.NS, "--timeout=120s"
        )
        forwards = fixture.Forwards()
        forwards.start("catalog-service", 19105, 9001)
        assert wait_status(200) == 200
        current = deployment()
        assert current["metadata"]["uid"] == original["metadata"]["uid"]
        assert current["spec"]["template"] == original["spec"]["template"]
        (base / "diagnostics" / "rollback-proof.json").write_text(
            json.dumps(
                {
                    "seeded_executor_fixture": True,
                    "independent_fault_status": 503,
                    "independent_recovered_status": 200,
                    "exact_template_restored": True,
                    "undo": actual.undo,
                    "seeded_policy_prerequisites": True,
                    "incident": actual.model_dump(mode="json"),
                    "not_evaluation_accuracy": True,
                },
                indent=2,
            )
        )
    finally:
        forwards.close()
        current = deployment()
        if current["metadata"]["uid"] != original["metadata"]["uid"]:
            raise RuntimeError("Identity changed, restoration refused")
        fixture.kubectl(
            "patch",
            "deployment/catalog-service",
            "-n",
            fixture.NS,
            "--type=json",
            "-p",
            json.dumps(
                [
                    {"op": "test", "path": "/metadata/uid", "value": original["metadata"]["uid"]},
                    {
                        "op": "test",
                        "path": "/metadata/resourceVersion",
                        "value": current["metadata"]["resourceVersion"],
                    },
                    {
                        "op": "replace",
                        "path": "/spec/template",
                        "value": original["spec"]["template"],
                    },
                ]
            ),
        )
        fixture.kubectl(
            "label",
            "deployment",
            "catalog-service",
            "-n",
            fixture.NS,
            "aegissre.managed=" + label if label is not None else "aegissre.managed-",
            "--overwrite",
        )
        fixture.kubectl(
            "rollout", "status", "deployment/catalog-service", "-n", fixture.NS, "--timeout=120s"
        )
    print(
        "Actual faulty image503 recovered200 through automatic scoped rollback. Seeded policy prerequisites, not diagnosis or evaluation accuracy."
    )


if __name__ == "__main__":
    main()
