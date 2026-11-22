#!/usr/bin/env python3
"""Actual evidence-only Ask via the running authenticated Compose gateway.

This proves persisted evidence/citations, not language-model inference.
"""

from __future__ import annotations

import urllib.error
from urllib.parse import quote

from check_gateway_stack import request


def main() -> None:
    try:
        request("/api/v1/ask", token=False, body={"service": "catalog-service", "question": "latency?"})
    except urllib.error.HTTPError as exc:
        assert exc.code == 401
    else:
        raise AssertionError("Ask accepted unauthenticated access")
    status = request("/api/v1/intelligence/status")
    assert status["provider"] == "disabled"
    assert status["write_tools"] == [] and status["automatic_retries"] == 0
    result = request("/api/v1/ask", body={"service": "catalog-service", "question": "What do the recent latency measurements and logs show?"})
    assert result["engine"] == "evidence-only-v1" and result["inference_status"] == "disabled"
    snapshot = result["snapshot"]
    assert snapshot["read_only"] and not snapshot["authorizes_actions"]
    assert snapshot["service"] == "catalog-service" and snapshot["environment"] == "dev"
    evidence = {item["id"]: item for item in snapshot["evidence"]}
    assert result["answer"]["evidence_ids"]
    assert set(result["answer"]["evidence_ids"]) <= set(evidence)
    assert {call["name"] for call in snapshot["tool_calls"]} == {"get_metrics", "get_logs", "get_traces", "get_health", "get_deployments", "get_k8s_events", "search_runbooks"}
    metrics = [item for item in snapshot["evidence"] if item["kind"] == "metric"]
    assert metrics, "No actually collected metrics reached Ask"
    for item in metrics:
        original = request("/api/v1/events/" + quote(item["source_ref"], safe=""))
        assert original["service"] == "catalog-service" and original["environment"] == "dev"
        assert original["payload"]["name"] == item["content"]["name"]
        assert original["payload"]["value"] == item["content"]["value"]
    assert any("No language model" in line for line in result["answer"]["limitations"])
    print("Actual read-only Ask, seven visible tools, persisted metric citations, scope and gateway auth passed; no LLM invoked")


if __name__ == "__main__":
    main()
