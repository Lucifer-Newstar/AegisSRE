#!/usr/bin/env python3
"""Actual gateway/metadata/SQL/Redis wiring using labelled synthetic CI inputs.

Not a real deployment fault, model-quality test or three-minute acceptance run.
Only the fresh disposable CI stack with its published fixture key is allowed.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

from check_gateway_stack import request as gateway_request
from check_runtime_stack import api, wait_for
from redis import Redis

STATE = Path("/tmp/aegis-deploy-window-fixture.json")
# Earlier gates intentionally deploy catalog-service. Keep this cohort separate
# so real overlap uncertainty is not mistaken for a failed positive-CFR check.
SERVICE = "payment-service"


def query(path: str, **params: str) -> dict:
    return gateway_request("/api/v1/deployment-intelligence/" + path + "?" + urlencode(params))


def record(identity: str) -> dict | None:
    return next(
        (
            row
            for row in query("rollouts", service=SERVICE)["rollouts"]
            if row["deployment_id"] == identity
        ),
        None,
    )


def seed() -> None:
    if STATE.exists():
        raise RuntimeError("Refusing to replace a prior fixture checkpoint")
    assert not query("rollouts", service=SERVICE)["rollouts"], "CI cohort already occupied"
    identity = "ci-window-" + uuid4().hex
    start = datetime.now(UTC) - timedelta(seconds=5)
    for index in range(12):
        api(
            "/events",
            body={
                "id": identity + "-warm-" + str(index),
                "source": "chaoslab",
                "type": "metric",
                "service": SERVICE,
                "environment": "dev",
                "timestamp": (start - timedelta(seconds=70 - index * 5)).isoformat(),
                "payload": {
                    "name": "latency_p95",
                    "labels": {"revision": identity},
                    "value": 0.1,
                    "unit": "seconds",
                },
            },
        )
    event_id = identity + "-deploy"
    api(
        "/deployments",
        port=8701,
        body={
            "id": event_id,
            "source": "deployment",
            "type": "deployment",
            "service": SERVICE,
            "environment": "dev",
            "timestamp": start.isoformat(),
            "payload": {
                "action": "deploy",
                "revision": identity,
                "previous_revision": "ci-previous",
                "deployment_id": identity,
                "started_at": start.isoformat(),
                "triggered_by": "explicit-synthetic-ci-fixture",
                "status": "succeeded",
            },
        },
    )
    wait_for(lambda: record(identity), "actual metadata-to-rollout collection")
    result = api(
        "/events",
        body={
            "id": identity + "-bad",
            "source": "chaoslab",
            "type": "metric",
            "service": SERVICE,
            "environment": "dev",
            "timestamp": (start + timedelta(seconds=1)).isoformat(),
            "payload": {
                "name": "latency_p95",
                "labels": {"revision": identity},
                "value": 9,
                "unit": "seconds",
            },
        },
    )
    assert result["anomalous"] is True
    row = wait_for(
        lambda: item if (item := record(identity)) and item["outcome"] == "bad" else None,
        "transactional rollout.bad",
    )
    STATE.write_text(
        json.dumps(
            {
                "identity": identity,
                "rollout_id": row["id"],
                "flagged_at": row["flagged_at"],
                "since": (start - timedelta(seconds=1)).isoformat(),
            }
        )
    )
    print(
        "Actual metadata/gateway/SQL deployment window marked bad from explicit synthetic CI telemetry; no workload action"
    )


def verify() -> None:
    saved = json.loads(STATE.read_text())
    row = wait_for(lambda: record(saved["identity"]), "persisted rollout after application restart")
    assert row["id"] == saved["rollout_id"] and row["outcome"] == "bad"
    assert row["flagged_at"] == saved["flagged_at"]
    assert row["ambiguous"] is False, "CI cohort overlapped another rollout"
    report = query("summary", service=SERVICE, since=saved["since"])
    assert report["identified_deployments"] == report["confirmed_bad"] == 1, report
    assert report["change_failure_rate"] == 1 and report["unknown_outcomes"] == 0
    redis = Redis.from_url("redis://127.0.0.1:6379/0", decode_responses=True)
    try:

        def published() -> bool:
            for _, fields in redis.xrevrange("st:rollout.bad", count=100):
                document = json.loads(fields["envelope"])
                if document["payload"].get("rollout_id") == saved["rollout_id"]:
                    assert document["payload"]["authorizes_execution"] is False
                    assert document["payload"]["causation_proven"] is False
                    return True
            return False

        wait_for(published, "actual Redis rollout.bad publication")
    finally:
        redis.close()
    print(
        "Actual restart-persistent rollout/CFR and Redis publication passed; synthetic fixture only, not real fault accuracy or latency acceptance"
    )


if __name__ == "__main__":
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("AEGIS_API_TOKEN") != "ci-disposable-runtime-token"
    ):
        raise SystemExit("Only the explicitly disposable CI runtime fixture may run this check")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("seed", "verify"))
    args = parser.parse_args()
    seed() if args.mode == "seed" else verify()
