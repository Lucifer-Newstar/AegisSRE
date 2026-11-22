#!/usr/bin/env python3
"""Actual pgvector-backed retrieval through the authenticated gateway."""

from __future__ import annotations

import urllib.error

from check_gateway_stack import request


def main() -> None:
    try:
        request("/api/v1/runbooks", token=False)
    except urllib.error.HTTPError as exc:
        assert exc.code == 401
    else:
        raise AssertionError("Knowledge API accepted an unauthenticated request")
    status = request("/api/v1/knowledge/status")
    assert status["enabled"] and status["backend"] == "pgvector"
    assert status["pgvector_version"] == "0.8.1"
    assert status["documents"] >= 20
    assert "not neural" in status["embedding_description"]
    assert len(request("/api/v1/runbooks")) == 10
    result = request("/api/v1/knowledge/search", body={"query": "Database connection refused timeout", "service": "catalog-service", "kind": "runbook"})
    assert result["environment"] == "dev"
    citations = [item for item in result["results"] if item["document_id"] == "runbook:database-outage"]
    assert citations
    document = request("/api/v1/runbooks/database-outage")
    for item in citations:
        assert item["retrieval_backend"] == "pgvector"
        assert item["id"].startswith(document["id"] + ":")
        assert item["content"] in document["content"]
        assert len(item["document_checksum"]) == 64
    print("Actual pgvector extension, scoped vector retrieval, cited packaged runbooks and gateway auth passed; no LLM invoked")


if __name__ == "__main__":
    main()
