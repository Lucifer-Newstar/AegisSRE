#!/usr/bin/env python3
"""Real retained-template rollback. Seeded executor proof, not DI-5 accuracy."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/ci"))
import kind_platform_gate as fixture  # noqa: E402
from incidents_service.config import Settings  # noqa: E402
from incidents_service.execution import Executor  # noqa: E402
from incidents_service.models import Plan  # noqa: E402


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
        assert status() == 503
        forwards.close()
        executor = Executor(
            Settings(
                api_token="disposable", executor="kubernetes", kube_context="kind-" + fixture.NAME
            )
        )
        result = executor.run(
            Plan(
                action="rollback",
                target="catalog-service",
                reason="Explicit retained-template fixture, not inferred diagnosis",
                risk="high",
                revision=revision,
                reversible=True,
            )
        )
        fixture.kubectl(
            "rollout", "status", "deployment/catalog-service", "-n", fixture.NS, "--timeout=120s"
        )
        forwards = fixture.Forwards()
        forwards.start("catalog-service", 19105, 9001)
        assert status() == 200
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
                    "undo": result.undo,
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
        "Actual faulty image503 recovered200 through retained-template scoped rollback. Seeded fixture, not automatic policy or evaluation claim."
    )


if __name__ == "__main__":
    main()
