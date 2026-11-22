#!/usr/bin/env python3
"""Exercise the actual Compose metadata APIs before and after process restart.

Only uses the local test stack. No cloud account or user data required; use disposable CI service credentials.
Run `--seed`, restart registry/deployments, then run `--verify`.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any


def request(port: int, path: str, method: str = "GET", body: Any = None, *, token: str | None = None) -> Any:
    raw = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=raw,
        method=method,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + (os.environ["AEGIS_METADATA_API_TOKEN"] if token is None else token)},
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        data = response.read()
        return json.loads(data) if data else None


def ready() -> None:
    for port in (8101, 8701):
        for attempt in range(60):
            try:
                assert request(port, "/ready")["status"] == "ready"
                break
            except (OSError, AssertionError):
                if attempt == 59:
                    raise
                time.sleep(1)


def seed() -> None:
    ready()
    for port, path in ((8101, "/services"), (8701, "/deployments")):
        try:
            request(port, path, token="")
        except urllib.error.HTTPError as error:
            assert error.code == 401
        else:
            raise AssertionError("Unauthenticated metadata read was accepted")
        assert isinstance(request(port, path, token=os.environ["AEGIS_METADATA_READ_TOKEN"]), list)
        try:
            request(port, path, "POST", {}, token=os.environ["AEGIS_METADATA_READ_TOKEN"])
        except urllib.error.HTTPError as error:
            assert error.code == 403
        else:
            raise AssertionError("Read-only metadata credential accepted a write")
    request(
        8101,
        "/services",
        "POST",
        {
            "id": "ml-service",
            "name": "CI metadata test",
            "url": "http://ml-service:8501",
            "owner": "CI fixture",
            "availability_slo": 0.995,
        },
    )
    request(8101, "/services/cart-service", "DELETE")
    request(
        8701,
        "/deployments",
        "POST",
        {
            "id": "ci-durable-deploy",
            "schema_version": "0.2",
            "source": "deployment",
            "type": "deployment",
            "service": "catalog-service",
            "timestamp": datetime.now(UTC).isoformat(),
            "payload": {
                "action": "deploy",
                "revision": "ci-test-revision",
                "triggered_by": "pipeline",
                "status": "succeeded",
            },
        },
    )
    print("Seeded controlled metadata fixtures into the running APIs")


def verify() -> None:
    ready()
    assert request(8101, "/services/ml-service")["owner"] == "CI fixture"
    assert request(8701, "/deployments/ci-durable-deploy")["revision"] == "ci-test-revision"
    try:
        request(8101, "/services/cart-service")
    except urllib.error.HTTPError as error:
        assert error.code == 404
    else:
        raise AssertionError("Deleted seed was resurrected after restart")
    print("Actual API restart persistence and deletion checks passed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--seed", action="store_true")
    group.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    seed() if args.seed else verify()


if __name__ == "__main__":
    main()
