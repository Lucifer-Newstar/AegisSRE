#!/usr/bin/env python3
"""Smoke the actual local CI gateway against disposable stack fixtures."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any


def request(path: str, *, token: bool = True, body: Any = None) -> Any:
    headers = {"Content-Type": "application/json", "X-Request-ID": "ci-gateway-proof"}
    if token:
        headers["Authorization"] = "Bearer " + os.environ["AEGIS_API_TOKEN"]
    req = urllib.request.Request(
        "http://127.0.0.1:8080" + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        assert response.headers["X-Request-ID"] == "ci-gateway-proof"
        return json.load(response)


def main() -> None:
    for attempt in range(90):
        try:
            assert request("/api/v1/ready")["status"] == "ready"
            break
        except (OSError, AssertionError):
            if attempt == 89:
                raise
            time.sleep(1)
    try:
        request("/api/v1/services", token=False)
    except urllib.error.HTTPError as exc:
        assert exc.code == 401
    else:
        raise AssertionError("Gateway accepted unauthenticated business access")
    services = request("/api/v1/services")
    assert any(row["id"] == "catalog-service" for row in services)
    incidents = request("/api/v1/incidents?service=ci-runtime")
    assert incidents
    incident_id = incidents[0]["id"]
    approved = request(
        f"/api/v1/incidents/{incident_id}/approve",
        body={
            "actor": "untrusted-client-label",
            "note": "CI approval fixture; execution is not requested",
        },
    )
    assert approved["approval"] == "approved" and approved["approved_by"] == "token:operator"
    audit = request(f"/api/v1/audit?incident_id={incident_id}")
    assert any(
        row["action"] == "remediation.approved" and row["actor"] == "token:operator"
        for row in audit
    )
    assert request("/api/v1/runtime")["enabled"]
    chart=request("/api/v1/metric-history?service=catalog-service&metric=latency_p95&hours=24&buckets=288")
    assert chart["status"]=="observed" and chart["source"]=="persisted-prometheus"
    assert chart["points"] and chart["missing_buckets"]>0
    for point in chart["points"]:
        evidence=request("/api/v1/events/"+point["evidence_id"])
        assert evidence["source"]=="prometheus" and evidence["service"]=="catalog-service"
        assert evidence["payload"]["name"]=="latency_p95"
        assert point["min"]<=evidence["payload"]["value"]<=point["max"]
    print("Actual persisted Prometheus metric-history buckets and evidence references passed; gaps retained")
    print(
        "Actual gateway auth, fixed routing, correlation and principal-bound approval passed; no execution requested"
    )


if __name__ == "__main__":
    main()
