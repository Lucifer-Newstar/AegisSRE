#!/usr/bin/env python3
"""Actual OTLP -> Loki/Tempo -> durable evidence join, not a chaos benchmark."""

from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Any
from uuid import uuid4


def read(path: str, *, port: int, headers: dict[str, str] | None = None) -> Any:
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers or {})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def main() -> None:
    # Exercise Tempo search/lookup canonicalization, including leading zeroes.
    identity = "00" + uuid4().hex[2:]
    headers = {"traceparent": f"00-{identity}-{uuid4().hex[:16]}-01"}
    authorization = {"Authorization": "Bearer " + os.environ["AEGIS_API_TOKEN"]}
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        assert read("/products", port=9001, headers=headers)
        logs = read("/events?service=catalog-service&environment=dev&event_type=log&limit=100", port=8201, headers=authorization)
        traces = read("/events?service=catalog-service&environment=dev&event_type=trace&limit=100", port=8201, headers=authorization)
        matching_logs = [event for event in logs if event.get("trace_id") == identity]
        matching_traces = [event for event in traces if event.get("trace_id") == identity]
        if matching_logs and matching_traces:
            assert any(event["payload"]["message"] == "listing products" for event in matching_logs)
            assert any(event["payload"]["name"] == "GET /products" for event in matching_traces)
            assert all(event["source"] == "loki" for event in matching_logs)
            assert all(event["source"] == "tempo" for event in matching_traces)
            print("Actual HTTP request logs and server spans joined by trace_id after durable Loki/Tempo collection")
            return
        time.sleep(0.5)
    status = read("/runtime", port=8201, headers=authorization)
    raise AssertionError(f"No durable trace/log join before deadline; runtime: {status}")


if __name__ == "__main__":
    main()
