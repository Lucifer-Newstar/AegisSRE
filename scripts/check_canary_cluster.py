#!/usr/bin/env python3
"""Two real catalog tracks, fixed Prometheus scrape labels, observed comparison.

Creates only new owned-fixture resources, restores Prometheus config in finally.
No deployment or rollback is authorized by the comparison verdict.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from threading import Event, Thread

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/ci"))
import kind_platform_gate as fixture  # noqa: E402

os.environ.update(fixture.FIXTURE)
from check_runtime_stack import api, wait_for  # noqa: E402


def main() -> None:
    if not fixture.owned():
        raise RuntimeError("Refusing unowned cluster")
    os.environ.update(fixture.FIXTURE)
    ns = fixture.NS

    def kube(*args: str) -> dict:
        return json.loads(fixture.kubectl(*args, "-n", ns, "-o", "json", capture=True))

    original = kube("get", "deployment", "catalog-service")
    prom = kube("get", "deployment", "prometheus")
    cm_name = next(
        v["configMap"]["name"]
        for v in prom["spec"]["template"]["spec"]["volumes"]
        if v["name"] == "platform-prometheus"
    )
    cm = kube("get", "configmap", cm_name)
    original_data = copy.deepcopy(cm["data"])
    forwards = fixture.Forwards()
    stop = Event()
    counts = {"stable": {"200": 0, "503": 0}, "canary": {"200": 0, "503": 0}}
    workers = []
    created: list[str] = []

    def traffic(track: str, port: int) -> None:
        while not stop.is_set():
            status = None
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/products", timeout=2
                ) as response:
                    status = str(response.status)
            except urllib.error.HTTPError as exc:
                status = str(exc.code)
            except OSError:
                pass
            if status in counts[track]:
                counts[track][status] += 1
            stop.wait(0.04)

    try:
        for track, port in [("stable", 19101), ("canary", 19102)]:
            name = "ci-catalog-" + track
            # Never patch the actual catalog or reuse a preexisting resource.
            for resource in ("deployment", "service"):
                check = fixture.kubectl(
                    "get", resource, name, "-n", ns, "--ignore-not-found", capture=True
                )
                if check.strip():
                    raise RuntimeError("Comparison resource already exists")
            spec = copy.deepcopy(original["spec"])
            spec["replicas"] = 1
            spec["selector"] = {"matchLabels": {"app": name}}
            spec["template"]["metadata"] = {
                "labels": {"app": name, "app.kubernetes.io/part-of": "aegisshop"}
            }
            if track == "canary":
                spec["template"]["spec"]["containers"][0]["image"] = (
                    "aegisshop/catalog-service:ci-faulty"
                )
            deployment = {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "metadata": {"name": name, "namespace": ns},
                "spec": spec,
            }
            service = {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {"name": name, "namespace": ns},
                "spec": {"selector": {"app": name}, "ports": [{"port": 9001, "targetPort": 9001}]},
            }
            created.append(name)
            fixture.kubectl(
                "create",
                "-f",
                "-",
                body=json.dumps(
                    {"apiVersion": "v1", "kind": "List", "items": [deployment, service]}
                ),
            )
            fixture.kubectl("rollout", "status", "deployment/" + name, "-n", ns, "--timeout=120s")
            forwards.start(name, port, 9001)
            worker = Thread(target=traffic, args=(track, port))
            worker.start()
            workers.append(worker)
        config = yaml.safe_load(original_data["prometheus.yml"])
        for track in ("stable", "canary"):
            config["scrape_configs"].append(
                {
                    "job_name": "ci-track-" + track,
                    "static_configs": [
                        {
                            "targets": ["ci-catalog-" + track + ":9001"],
                            "labels": {
                                "service": "catalog-service",
                                "environment": "dev",
                                "track": track,
                            },
                        }
                    ],
                }
            )
        changed = {**original_data, "prometheus.yml": yaml.safe_dump(config)}
        fixture.kubectl(
            "patch",
            "configmap",
            cm_name,
            "-n",
            ns,
            "--type=merge",
            "-p",
            json.dumps({"data": changed}),
        )
        fixture.kubectl("rollout", "restart", "deployment/prometheus", "-n", ns)
        fixture.kubectl(
            "rollout", "status", "deployment/prometheus", "-n", ns, "--timeout=180s", timeout=200
        )
        forwards.start("incidents-service", 8201, 8201)

        def compared() -> dict | None:
            result = api("/deployment-intelligence/canary?service=catalog-service")
            return result if result["status"] == "regressed" else None

        result = wait_for(compared, "actual separately scraped canary regression", 150)
        assert counts["stable"]["200"] >= 100 and counts["canary"]["503"] >= 100
        assert result["tracks"]["stable"]["error_ratio"] < 0.01
        assert result["tracks"]["canary"]["error_ratio"] > 0.9
        (fixture.directory() / "diagnostics" / "canary-proof.json").write_text(
            json.dumps(
                {
                    "actual_comparison": result,
                    "independent_response_counts": counts,
                    "fixture_traffic_split": "roughly equal direct requests to independent tracks, not production routing",
                    "not_evaluation_accuracy": True,
                },
                indent=2,
            )
        )
        forwards.start("api-gateway", 8080, 8000)
        forwards.start("console", 3030, 3030)
        subprocess.run(
            ["node", str(ROOT / "scripts/visual/console.mjs")],
            env={
                **os.environ,
                "AEGIS_VISUAL_OUTPUT": str(fixture.directory() / "diagnostics" / "canary-visual"),
                "AEGIS_REQUIRE_CANARY": "true",
            },
            check=True,
            timeout=120,
        )
        print(
            "Actual normal/faulty catalog track traffic independently scraped and regression visible through authenticated API"
        )
    finally:
        stop.set()
        for worker in workers:
            worker.join(timeout=5)
        forwards.close()
        fixture.kubectl(
            "patch",
            "configmap",
            cm_name,
            "-n",
            ns,
            "--type=merge",
            "-p",
            json.dumps({"data": original_data}),
        )
        fixture.kubectl("rollout", "restart", "deployment/prometheus", "-n", ns)
        fixture.kubectl(
            "rollout", "status", "deployment/prometheus", "-n", ns, "--timeout=180s", timeout=200
        )
        for name in created:
            fixture.kubectl(
                "delete",
                "deployment,service",
                name,
                "-n",
                ns,
                "--ignore-not-found",
            )


if __name__ == "__main__":
    main()
