from __future__ import annotations

import os
from uuid import uuid4

import pytest
from incidents_service.knowledge import DIMENSIONS, KnowledgeDocument, KnowledgeStore
from incidents_service.repository import Repository
from sqlalchemy import text


@pytest.mark.skipif(
    not os.environ.get("AEGIS_TEST_DATABASE_URL"),
    reason="Requires isolated actual PostgreSQL with pgvector",
)
def test_actual_pgvector_storage_distance_scope_and_restart() -> None:
    url = os.environ["AEGIS_TEST_DATABASE_URL"]
    identity = "pgvector-test:" + uuid4().hex
    environment = "rag-" + uuid4().hex[:8]
    repo = Repository(url)
    store = KnowledgeStore(repo)
    assert store.backend == "pgvector"
    assert store.counts()["pgvector_version"]
    source = KnowledgeDocument(
        id=identity,
        kind="runbook",
        title="Database connection refused",
        content="Database connection refused timeout unavailable",
        service="catalog-service",
        environment=environment,
        source="integration:actual-pgvector",
    )
    store.upsert(source)
    with repo.transaction() as tx:
        row = (
            tx.conn.execute(
                text(
                    "SELECT pg_typeof(embedding)::text AS kind, vector_dims(embedding) AS dimensions, embedding <=> embedding AS distance FROM aegis_knowledge_chunks WHERE document_id=:id"
                ),
                {"id": identity},
            )
            .mappings()
            .one()
        )
        assert row["kind"] == "vector"
        assert row["dimensions"] == DIMENSIONS
        assert row["distance"] == pytest.approx(0, abs=1e-6)
    results = store.search(
        "database connection refused timeout",
        service="catalog-service",
        environment=environment,
        kind="runbook",
    )
    assert any(item["document_id"] == identity for item in results)
    assert all(item["retrieval_backend"] == "pgvector" for item in results)
    assert store.get_document(identity, service="cart-service", environment=environment) is None
    assert store.get_document(identity, service="catalog-service", environment="other") is None
    repo.close()
    restarted = Repository(url)
    store = KnowledgeStore(restarted)
    assert (
        store.get_document(identity, service="catalog-service", environment=environment)
        == source.model_dump()
    )
    store.delete_document(identity)
    restarted.close()
