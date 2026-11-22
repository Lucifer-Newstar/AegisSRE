#!/usr/bin/env python3
"""Actual Compose wiring proof, not chaos accuracy or an acceptance benchmark.

Uses only a fresh disposable local CI stack. Inputs explicitly labelled as CI
fixtures prove transport, persistence and recovery, not a real workload failure.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from redis import Redis

STATE = Path("/tmp/aegis-runtime-fixture.json")
TOKEN = os.environ["AEGIS_API_TOKEN"]


def api(path: str, *, port: int = 8201, body: Any = None, authorized: bool = True) -> Any:
    headers = {"Content-Type": "application/json"}
    if authorized and port == 8201:
        headers["Authorization"] = f"Bearer {TOKEN}"
    if authorized and port in (8101, 8701):
        headers["Authorization"] = "Bearer " + os.environ["AEGIS_METADATA_API_TOKEN"]
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def wait_for(check: Any, description: str, seconds: int = 90) -> Any:
    deadline = time.monotonic() + seconds
    last = "condition not met"
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except (OSError, AssertionError, ValueError, KeyError) as exc:
            last = type(exc).__name__
        time.sleep(0.5)
    raise AssertionError(f"Timed out waiting for {description}: {last}")


def seed() -> None:
    wait_for(lambda: api("/ready")["status"] == "ready", "authenticated runtime readiness")
    try:
        api("/incidents", authorized=False)
    except urllib.error.HTTPError as exc:
        assert exc.code == 401
    else:
        raise AssertionError("Runtime accepted an unauthenticated business request")
    deployment = {
        "id": "ci-runtime-deploy",
        "schema_version": "0.2",
        "source": "deployment",
        "type": "deployment",
        "service": "catalog-service",
        "environment": "dev",
        "timestamp": datetime.now(UTC).isoformat(),
        "payload": {
            "action": "deploy",
            "revision": "ci-observed-revision",
            "status": "succeeded",
            "triggered_by": "ci-fixture",
        },
    }
    api("/deployments", port=8701, body=deployment)
    wait_for(
        lambda: api("/events/ci-runtime-deploy")["payload"]["revision"] == "ci-observed-revision",
        "deployment polling through durable outbox and Redis",
    )

    # Exercise the running demo service so counters, histograms and process
    # samples exist in actual Prometheus, not a mocked query response.
    def observed_metrics() -> bool:
        api("/products", port=9001)
        events = api("/events?service=catalog-service&event_type=metric&limit=500")
        names = {event["payload"]["name"] for event in events if event["source"] == "prometheus"}
        return {
            "cpu_usage_percent",
            "memory_bytes",
            "request_rate",
            "latency_p95",
            "error_rate",
        } <= names

    wait_for(observed_metrics, "actual scoped Prometheus rates, histogram and process metrics", 120)
    runtime = api("/runtime")
    assert runtime["collector_enabled"] and not runtime["collector_failures"]

    redis = Redis.from_url("redis://127.0.0.1:6379/0", decode_responses=True)
    try:
        point = datetime.now(UTC) - timedelta(seconds=30)
        for index in range(13):
            event = {
                "id": f"ci-runtime-metric-{index}",
                "schema_version": "0.2",
                "timestamp": (point + timedelta(seconds=index)).isoformat(),
                "source": "chaoslab",
                "type": "metric",
                "service": "ci-runtime",
                "environment": "dev",
                "payload": {
                    "name": "memory_bytes",
                    "unit": "bytes",
                    "value": 900 if index == 12 else 100,
                    "labels": {"fixture": "transport-not-real-fault"},
                },
            }
            redis.xadd("st:metric", {"envelope": json.dumps(event)})

        def fixture_incident() -> Any:
            records = api("/incidents?service=ci-runtime")
            return records[0] if records else None

        incident = wait_for(fixture_incident, "Redis input becoming a persisted incident")
        assert incident["status"] == "investigating"
        assert incident["signals"][0]["event_id"] == "ci-runtime-metric-12"
        for kind in ("anomaly", "incident", "audit"):

            def output_seen(event_type: str = kind) -> bool:
                return any(
                    json.loads(fields["envelope"])["service"] == "ci-runtime"
                    for _, fields in redis.xrange(f"st:{event_type}", count=1000)
                )

            wait_for(output_seen, f"transactional {kind} outbox dispatch")
        redis.xadd("st:metric", {"envelope": "ci malformed-envelope fixture"})
        wait_for(lambda: redis.xlen("dlq:metric") > 0, "explicit poison quarantine")

        pending = {
            "id": "ci-pending-after-restart",
            "schema_version": "0.2",
            "timestamp": datetime.now(UTC).isoformat(),
            "source": "chaoslab",
            "type": "health",
            "service": "ci-runtime",
            "environment": "dev",
            "payload": {"status": "unknown", "fixture": "crashed-consumer"},
        }
        # Atomic publish+claim creates a genuinely pending entry owned by a
        # consumer that never ACKs. The restarted runtime must reclaim it.
        with redis.pipeline(transaction=True) as pipeline:
            pipeline.xadd("st:health", {"envelope": json.dumps(pending)})
            pipeline.xreadgroup("reliability-v1", "ci-crashed", {"st:health": ">"}, count=100)
            results = pipeline.execute()
        assert results[1], "Could not create a pending consumer entry"
        claimed = redis.xpending_range(
            "st:health", "reliability-v1", min=results[0], max=results[0], count=1
        )
        assert claimed and claimed[0]["consumer"] == "ci-crashed"
        STATE.write_text(
            json.dumps({"incident_id": incident["id"], "consumer": runtime["delivery_consumer"]})
        )
        print("Actual Prometheus, deployment, Redis/SQL/outbox and poison checks passed")
    finally:
        redis.close()


def verify() -> None:
    fixture = json.loads(STATE.read_text())
    wait_for(lambda: api("/ready")["status"] == "ready", "restarted runtime readiness")
    assert api("/runtime")["delivery_consumer"] != fixture["consumer"]
    incident = api(f"/incidents/{fixture['incident_id']}")
    assert incident["service"] == "ci-runtime" and incident["status"] == "investigating"
    assert api("/events/ci-runtime-metric-12")["payload"]["value"] == 900
    wait_for(
        lambda: api("/events/ci-pending-after-restart")["payload"]["fixture"] == "crashed-consumer",
        "pending delivery reclaimed after restart",
        90,
    )
    assert len(api(f"/audit?incident_id={fixture['incident_id']}")) >= 2
    print("Actual application restart retained business state and recovered pending Redis input")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["seed", "verify"])
    seed() if parser.parse_args().mode == "seed" else verify()


if __name__ == "__main__":
    main()
