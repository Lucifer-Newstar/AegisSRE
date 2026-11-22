from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from incidents_service.config import Settings
from incidents_service.knowledge import KnowledgeDocument, KnowledgeStore
from incidents_service.knowledge_indexer import KnowledgeIndexer
from incidents_service.models import Analysis, Incident, Plan
from incidents_service.repository import Repository

QUERIES = {
    "cpu-saturation": "CPU usage is pegged and requests are slow",
    "memory-exhaustion": "OOMKilled processes and growing resident memory",
    "container-crash": "CrashLoopBackOff with repeated container restarts",
    "database-outage": "Postgres connection refused and database unavailable",
    "network-latency": "Network packet delay and connection timed out",
    "http-5xx": "Many HTTP 500 internal server error responses",
    "dependency-failure": "Upstream dependency unavailable and downstream failures",
    "config-error": "Missing configuration after a setting change",
    "faulty-deployment": "New deployment revision caused an error regression",
    "traffic-spike": "Unexpected surge of requests and request rate above baseline",
}


def document(identity: str = "test", **overrides: Any) -> KnowledgeDocument:
    return KnowledgeDocument.model_validate(
        {
            "id": identity,
            "kind": "runbook",
            "title": "Database timeout",
            "content": "Database connection refused and timeout investigation",
            "source": "test:fixture",
            **overrides,
        }
    )


def test_scoped_retrieval_and_content_updates_remove_old_chunks() -> None:
    repo = Repository("sqlite:///:memory:")
    store = KnowledgeStore(repo)
    assert store.upsert(
        document(
            service="catalog-service",
            environment="dev",
            content="Database timeout investigation " * 100,
        )
    )
    assert not store.upsert(
        document(
            service="catalog-service",
            environment="dev",
            content="Database timeout investigation " * 100,
        )
    )
    assert store.counts()["chunks"] > 1
    assert store.search("database timeout", service="catalog-service", environment="dev")
    assert not store.search("database timeout", service="cart-service", environment="dev")
    assert not store.search("database timeout", service="catalog-service", environment="prod")
    store.upsert(
        document(service="catalog-service", environment="dev", content="Database timeout fixed")
    )
    assert store.counts()["chunks"] == 1
    assert store.backend == "sqlite_exact_cosine"
    assert store.counts()["pgvector_version"] is None
    store.delete_document("test")
    assert store.counts()["documents"] == store.counts()["chunks"] == 0
    repo.close()


def test_local_runbooks_patterns_and_synthetic_retrieval_regression() -> None:
    repo = Repository("sqlite:///:memory:")
    store = KnowledgeStore(repo)
    indexer = KnowledgeIndexer(store, Settings(dev_mode=True))
    assert indexer.seed() == 20
    assert indexer.seed() == 0
    assert (
        len(store.list_documents(kind="runbook", service="catalog-service", environment="dev"))
        == 10
    )
    assert (
        len(
            store.list_documents(
                kind="failure_pattern", service="catalog-service", environment="dev"
            )
        )
        == 10
    )
    hits = sum(
        any(
            item["document_id"] == "runbook:" + expected
            for item in store.search(
                query, service="catalog-service", environment="dev", kind="runbook"
            )
        )
        for expected, query in QUERIES.items()
    )
    # This is a small authored regression corpus, not the real chaos benchmark.
    assert hits / len(QUERIES) >= 0.8
    assert store.search("the and or", service="catalog-service", environment="dev") == []
    with pytest.raises(ValueError):
        store.search("too many", service="catalog-service", environment="dev", limit=1000)
    indexer.close()
    repo.close()


def test_metadata_index_is_scoped_and_deleted_services_are_removed() -> None:
    from incidents_service.collectors import ReadClient

    repo = Repository("sqlite:///:memory:")
    store = KnowledgeStore(repo)
    records = [
        {
            "id": "catalog-service",
            "name": "Catalog",
            "owner": "catalog-team",
            "url": "http://must-not-be-indexed.invalid",
            "availability_slo": 0.999,
        },
        {"id": "other-service", "name": "Outside scope"},
    ]
    config = Settings(
        dev_mode=True, registry_url="http://registry", allowed_targets=["catalog-service"]
    )
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=records))
    ) as client:
        indexer = KnowledgeIndexer(store, config, ReadClient(client))
        indexer.refresh()
        docs = store.list_documents(kind="service", service="catalog-service", environment="dev")
        assert len(docs) == 1
        assert "must-not-be-indexed" not in json.dumps(docs)
        assert not store.list_documents(
            kind="service", service="catalog-service", environment="prod"
        )
        records.clear()
        indexer.refresh()
        assert not store.list_documents(
            kind="service", service="catalog-service", environment="dev"
        )
    repo.close()


def test_closed_incidents_are_indexed_without_claiming_verified_cause() -> None:
    repo = Repository("sqlite:///:memory:")
    store = KnowledgeStore(repo)
    incident = Incident(
        id="closed-test",
        service="catalog-service",
        environment="dev",
        title="Memory problem",
        status="closed",
        signals=[],
        evidence_ids=["evidence-1"],
        analysis=Analysis(
            summary="Possible memory exhaustion", confidence="low", evidence_ids=["evidence-1"]
        ),
        plan=Plan(action="escalate", target="catalog-service", reason="Fixture", risk="high"),
        audit=[],
    )
    with repo.transaction() as tx:
        tx.save_incident(incident)
    indexer = KnowledgeIndexer(store, Settings(dev_mode=True))
    indexer.refresh()
    docs = store.list_documents(kind="incident", service="catalog-service", environment="dev")
    assert len(docs) == 1
    body = json.loads(docs[0]["content"])
    assert body["simulation"] is True
    assert "not proof" in body["cause_caveat"]
    assert not store.list_documents(kind="incident", service="catalog-service", environment="prod")
    indexer.close()
    repo.close()


