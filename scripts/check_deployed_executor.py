#!/usr/bin/env python3
"""Seeded plan proves deployed API execution identity; not detector accuracy."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts/ci"))
import kind_platform_gate as fixture  # type: ignore[import-not-found] # noqa: E402

SEED = """
from incidents_service.config import Settings
from incidents_service.repository import Repository
from incidents_service.models import Incident,Analysis,Plan
config=Settings()
with Repository(config.database_url).transaction() as tx:
    if tx.incident('deployed-executor-proof'):
        raise RuntimeError('Refusing repeated executor fixture')
    tx.save_incident(Incident(id='deployed-executor-proof',service='catalog-service',environment='dev',title='Seeded API scale proof, not diagnosis',status='investigating',signals=[],evidence_ids=[],audit=[],analysis=Analysis(summary='Explicit integration fixture',confidence='low',evidence_ids=[]),plan=Plan(action='scale',target='catalog-service',replicas=2,reason='Explicit fixture',risk='low',reversible=True)))
"""


def main() -> None:
    if not fixture.owned():
        raise RuntimeError("Refusing unowned cluster")
    os.environ.update(fixture.FIXTURE)
    sys.path.insert(0, str(ROOT / "scripts"))
    from scripts.check_gateway_stack import request
    from scripts.check_runtime_stack import wait_for
    from scripts.enable_scoped_executor import enable

    def deployment() -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(fixture.kubectl("get", "deployment/catalog-service", "-n", fixture.NS,
                                         "-o", "json", capture=True)))
    original = deployment()
    if original["spec"]["replicas"] != 1:
        raise RuntimeError("One replica required before deployed proof")
    label = original["metadata"].get("labels", {}).get("aegissre.managed")
    forwards = fixture.Forwards()
    try:
        enable()
        subject = "system:serviceaccount:" + fixture.NS + ":aegissre-executor"
        for verb, resource, expected in [("patch", "deployment/catalog-service", "yes"),
            ("patch", "deployment/incidents-service", "no"), ("get", "secrets", "no"),
            ("create", "pods/exec", "no"), ("delete", "pods", "no")]:
            # kubectl auth can-i exits1 for denied, so inspect via fixed exec subprocess.
            import subprocess
            result = subprocess.run([str(fixture.directory()/"bin/kubectl"),
                "--kubeconfig", str(fixture.directory()/"kubeconfig"),
                "--context", "kind-"+fixture.NAME, "auth", "can-i", verb, resource,
                "-n", fixture.NS, "--as="+subject], capture_output=True, text=True, check=False)
            assert result.stdout.strip() == expected
        fixture.kubectl("label", "deployment/catalog-service", "-n", fixture.NS,
                        "aegissre.managed=true", "--overwrite")
        fixture.kubectl("exec", "deployment/incidents-service", "-n", fixture.NS,
                        "--", "python", "-c", SEED)
        forwards.start("api-gateway", 8080, 8000)
        wait_for(lambda: request("/api/v1/autonomy")["executor"] == "kubernetes", "actual deployed executor")
        request("/api/v1/incidents/deployed-executor-proof/approve", body={"actor":"fixture","note":"Explicit integration approval"})
        request("/api/v1/autonomy", body={"mode":"recommend","actor":"fixture"})
        result = request("/api/v1/actions/deployed-executor-proof/execute", body={"actor":"fixture"})
        assert result["status"] == "verifying" and result["undo"]["executor"] == "kubernetes"
        changed = deployment()
        assert changed["metadata"]["uid"] == original["metadata"]["uid"]
        assert changed["spec"]["replicas"] == 2
        assert any(a["action"]=="remediation.started" and a["actor"]=="token:operator" for a in result["audit"])
        request("/api/v1/autonomy", body={"mode":"observe","actor":"fixture"})
        (fixture.directory()/"diagnostics"/"deployed-executor-proof.json").write_text(json.dumps({
            "seeded_plan_not_diagnosis":True,"deployed_api_executor":True,
            "replicas_before":1,"replicas_after":2,"uid":changed["metadata"]["uid"],
            "actor":"token:operator","mode_after":"observe","rbac_denials_verified":True,
            "not_autonomy_or_recovery_accuracy":True},indent=2))
    finally:
        # Explicit safety stop even if result checks failed. Never replay execute.
        try:
            request("/api/v1/autonomy", body={"mode":"observe","actor":"fixture-cleanup"})
        except Exception:
            # Durable local audit remains available; fail closed at the workload
            # boundary as well, with no further executor call.
            fixture.kubectl("set", "env", "deployment/incidents-service", "-n", fixture.NS,
                            "AEGIS_EXECUTOR=simulation")
        fixture.kubectl("scale", "deployment/catalog-service", "-n", fixture.NS, "--replicas=1")
        fixture.kubectl("label", "deployment/catalog-service", "-n", fixture.NS,
            "aegissre.managed="+label if label is not None else "aegissre.managed-", "--overwrite")
        forwards.close()


if __name__ == "__main__":
    main()
