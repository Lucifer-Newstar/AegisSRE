#!/usr/bin/env python3
"""Measure actual restarted application telemetry through Grafana within60s.

This isolates application startup with collectors already running. It is not a
cold bootstrap timing result for cluster/images/databases/Grafana together.
"""
from __future__ import annotations

import base64
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/ci"))
import kind_platform_gate as fixture  # type: ignore[import-not-found] # noqa: E402


def main() -> None:
    if not fixture.owned():
        raise RuntimeError("Refusing unowned cluster")
    forwards = fixture.Forwards()
    auth = base64.b64encode(b"admin:ci-disposable-grafana").decode()
    try:
        forwards.start("grafana", 13000, 3000)
        before = json.loads(fixture.kubectl("get", "pods", "-n", fixture.NS,
            "-l", "app.kubernetes.io/name=catalog-service", "-o", "json", capture=True))
        old = {p["metadata"]["uid"] for p in before["items"]}
        fixture.kubectl("rollout", "restart", "deployment/catalog-service", "-n", fixture.NS)
        deadline = time.monotonic() + 120
        proof: dict[str, Any] | None = None
        errors: list[str] = []
        while time.monotonic() < deadline:
            try:
                pods = json.loads(fixture.kubectl("get", "pods", "-n", fixture.NS,
                    "-l", "app.kubernetes.io/name=catalog-service", "-o", "json", capture=True))["items"]
                fresh = [p for p in pods if p["metadata"]["uid"] not in old
                         and p["status"].get("podIP") and not p["metadata"].get("deletionTimestamp")]
                if len(fresh) != 1:
                    time.sleep(1)
                    continue
                pod = fresh[0]
                statuses = pod["status"].get("containerStatuses", [])
                running = next((s["state"]["running"] for s in statuses
                                if s["name"] == "catalog-service" and "running" in s["state"]), None)
                if running is None:
                    time.sleep(1)
                    continue
                started = datetime.fromisoformat(running["startedAt"].replace("Z", "+00:00")).timestamp()
                instance = "catalog-service:9001"
                # Current scrape must be for the newly started Pod, never old series.
                query = 'process_start_time_seconds{job="aegisshop-catalog",instance="' + instance + '"}'
                url = "http://127.0.0.1:13000/api/datasources/proxy/uid/prometheus/api/v1/query?"
                request = urllib.request.Request(url + urllib.parse.urlencode({"query": query}),
                    headers={"Authorization": "Basic " + auth})
                with urllib.request.urlopen(request, timeout=3) as response:
                    result = json.load(response)["data"]["result"]
                now = time.time()
                valid = [r for r in result if float(r["value"][1]) >= started - 1]
                if valid:
                    elapsed = now - started
                    if not 0 <= elapsed < 60:
                        raise AssertionError("New-Pod metric missed60s startup budget")
                    proof = {"container_started_at": running["startedAt"],
                        "pod_uid": pod["metadata"]["uid"], "instance": instance,
                        "observed_via": "authenticated Grafana provisioned Prometheus datasource",
                        "query": query, "result": valid,
                        "seconds_from_container_start_to_observation": elapsed,
                        "under60_seconds": True, "collectors_already_running": True,
                        "not_cold_full_stack_bootstrap": True}
                    break
            except (OSError, ValueError, KeyError) as error:
                errors.append(type(error).__name__)
            time.sleep(1)
        if proof is None:
            raise AssertionError("New-Pod telemetry unavailable through Grafana: " + str(errors[-5:]))
        output = fixture.directory() / "diagnostics" / "startup-grafana-proof.json"
        output.write_text(json.dumps(proof, indent=2))
    finally:
        forwards.close()
    print("Fresh application process metric reached authenticated Grafana datasource within60s; collectors were already running")


if __name__ == "__main__":
    main()
