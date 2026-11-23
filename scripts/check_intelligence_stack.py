#!/usr/bin/env python3
"""Actual evidence-only Ask via the running authenticated Compose gateway.

This proves persisted evidence/citations, not language-model inference.
"""

from __future__ import annotations

import urllib.error
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from check_gateway_stack import request
from check_runtime_stack import api


def main() -> None:
    try:
        request(
            "/api/v1/ask", token=False, body={"service": "catalog-service", "question": "latency?"}
        )
    except urllib.error.HTTPError as exc:
        assert exc.code == 401
    else:
        raise AssertionError("Ask accepted unauthenticated access")
    status = request("/api/v1/intelligence/status")
    assert status["provider"] == "disabled"
    assert status["write_tools"] == [] and status["automatic_retries"] == 0
    result = request(
        "/api/v1/ask",
        body={
            "service": "catalog-service",
            "question": "What do the recent latency measurements and logs show?",
        },
    )
    assert result["engine"] == "evidence-only-v1" and result["inference_status"] == "disabled"
    snapshot = result["snapshot"]
    assert snapshot["read_only"] and not snapshot["authorizes_actions"]
    assert snapshot["service"] == "catalog-service" and snapshot["environment"] == "dev"
    evidence = {item["id"]: item for item in snapshot["evidence"]}
    assert result["answer"]["evidence_ids"]
    assert set(result["answer"]["evidence_ids"]) <= set(evidence)
    assert {call["name"] for call in snapshot["tool_calls"]} == {
        "get_metrics",
        "get_logs",
        "get_traces",
        "get_health",
        "get_deployments",
        "get_k8s_events",
        "search_runbooks",
    }
    metrics = [item for item in snapshot["evidence"] if item["kind"] == "metric"]
    assert metrics, "No actually collected metrics reached Ask"
    for item in metrics:
        original = request("/api/v1/events/" + quote(item["source_ref"], safe=""))
        assert original["service"] == "catalog-service" and original["environment"] == "dev"
        assert original["payload"]["name"] == item["content"]["name"]
        assert original["payload"]["value"] == item["content"]["value"]
    assert any("No language model" in line for line in result["answer"]["limitations"])
    # Explicit synthetic CI history, not a real fault or benchmark result.
    # Live resource telemetry can legitimately open unrelated payment incidents.
    # Isolation is by the dedicated metric/labels and exact source-event IDs,
    # not by assuming that a healthy service never has statistical novelty.
    existing = request("/api/v1/incidents?service=payment-service")
    assert not any("ci-history-qualifying" in item.get("evidence_ids", []) for item in existing)
    anchor = datetime.now(UTC) - timedelta(days=1)

    def fixture(identity: str, at: datetime, value: float) -> dict[str, object]:
        return {
            "id": identity,
            "source": "chaoslab",
            "type": "metric",
            "service": "payment-service",
            "environment": "dev",
            "timestamp": at.isoformat(),
            "payload": {
                "name": "ci_historical_latency",
                "value": value,
                "labels": {"fixture": "synthetic-history-not-a-real-fault"},
            },
        }

    for index in range(12):
        api(
            "/events",
            body=fixture(f"ci-history-normal-{index}", anchor - timedelta(seconds=12 - index), 0.1),
        )
    detected = api("/events", body=fixture("ci-history-qualifying", anchor, 4))
    assert detected["anomalous"] and detected["incident_id"]
    for index in range(2):
        api(
            "/events",
            body=fixture(f"ci-history-later-{index}", anchor + timedelta(seconds=index + 1), 0.1),
        )
    api("/events", body=fixture("ci-history-current-recovery", datetime.now(UTC), 0.1))
    identity = detected["incident_id"]
    before = request("/api/v1/incidents/" + identity)
    investigation = request("/api/v1/incidents/" + identity + "/investigate", body={})
    history = investigation["result"]["snapshot"]
    assert history["temporal_scope"] == "incident_window"
    references = {item["source_ref"] for item in history["evidence"]}
    assert "ci-history-qualifying" in references
    assert "ci-history-current-recovery" not in references
    assert not investigation["authorizes_actions"]
    after = request("/api/v1/incidents/" + identity)
    assert after == before
    print(
        "Actual historical incident window and qualifying-event preservation passed with labelled synthetic CI history; no real fault, inference or action"
    )
    print(
        "Actual read-only Ask, seven visible tools, persisted metric citations, scope and gateway auth passed; no LLM invoked"
    )


if __name__ == "__main__":
    main()
