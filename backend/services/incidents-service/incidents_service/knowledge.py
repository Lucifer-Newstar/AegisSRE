"""Cited, scoped retrieval with real pgvector and an explicit SQLite test fallback.

The built-in embedding is local lexical hashing, NOT a neural embedding model.
No model weights, hosted inference or network calls are needed for indexing.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from pydantic import Field
from sklearn.feature_extraction.text import HashingVectorizer  # type: ignore[import-untyped]
from sqlalchemy import text

from incidents_service.models import StrictModel, now
from incidents_service.repository import Repository

DIMENSIONS = 768
EMBEDDING = "lexical-hashing-word-bigrams-v1-768"
_vectorizer = HashingVectorizer(
    n_features=DIMENSIONS, alternate_sign=False, norm="l2", stop_words="english", ngram_range=(1, 2)
)


class KnowledgeDocument(StrictModel):
    id: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9:_-]+$")
    kind: str = Field(pattern=r"^(runbook|incident|service|failure_pattern)$")
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=40000)
    service: str = Field(default="*", min_length=1, max_length=63)
    environment: str = Field(default="*", min_length=1, max_length=40)
    source: str = Field(min_length=1, max_length=300)


def embed(value: str) -> list[float]:
    return [float(item) for item in _vectorizer.transform([value]).toarray()[0]]


def chunks(content: str) -> list[str]:
    # Overlap keeps a heading and the first check together across boundaries.
    return [content[offset : offset + 1400] for offset in range(0, len(content), 1200)]


class KnowledgeStore:
    def __init__(self, repository: Repository):
        self.repo = repository
        self.postgres = repository.engine.dialect.name == "postgresql"
        self.backend = "pgvector" if self.postgres else "sqlite_exact_cosine"
        vector_type = f"vector({DIMENSIONS})" if self.postgres else "TEXT"
        with self.repo.transaction() as tx:
            if self.postgres:
                tx.conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            tx.conn.execute(
                text("""CREATE TABLE IF NOT EXISTS aegis_knowledge_documents (
                id VARCHAR(120) PRIMARY KEY, kind VARCHAR(30) NOT NULL,
                service VARCHAR(63) NOT NULL, environment VARCHAR(40) NOT NULL,
                checksum VARCHAR(64) NOT NULL, document TEXT NOT NULL, updated_at VARCHAR(40) NOT NULL
            )""")
            )
            # The interpolated type is selected exclusively by trusted code.
            tx.conn.execute(
                text(f"""CREATE TABLE IF NOT EXISTS aegis_knowledge_chunks (
                id VARCHAR(160) PRIMARY KEY, document_id VARCHAR(120) NOT NULL,
                service VARCHAR(63) NOT NULL, environment VARCHAR(40) NOT NULL,
                embedding_model VARCHAR(80) NOT NULL, content TEXT NOT NULL,
                embedding {vector_type} NOT NULL
            )""")
            )
            tx.conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS aegis_knowledge_scope ON aegis_knowledge_chunks(service, environment)"
                )
            )

    def upsert(self, document: KnowledgeDocument) -> bool:
        serialized = document.model_dump_json()
        checksum = hashlib.sha256((EMBEDDING + serialized).encode()).hexdigest()
        with self.repo.transaction() as tx:
            current = tx.conn.execute(
                text("SELECT checksum FROM aegis_knowledge_documents WHERE id=:id"),
                {"id": document.id},
            ).scalar_one_or_none()
            if current == checksum:
                return False
        pieces = [
            (
                f"{document.id}:{checksum[:12]}:{index}",
                part,
                json.dumps(embed(document.title + "\n" + part)),
            )
            for index, part in enumerate(chunks(document.content))
        ]
        with self.repo.transaction() as tx:
            existing = tx.conn.execute(
                text("SELECT checksum FROM aegis_knowledge_documents WHERE id=:id"),
                {"id": document.id},
            ).scalar_one_or_none()
            if existing == checksum:
                return False
            tx.conn.execute(
                text("DELETE FROM aegis_knowledge_chunks WHERE document_id=:id"),
                {"id": document.id},
            )
            tx.conn.execute(
                text("DELETE FROM aegis_knowledge_documents WHERE id=:id"), {"id": document.id}
            )
            tx.conn.execute(
                text(
                    "INSERT INTO aegis_knowledge_documents (id,kind,service,environment,checksum,document,updated_at) VALUES (:id,:kind,:service,:environment,:checksum,:document,:updated_at)"
                ),
                {
                    "id": document.id,
                    "kind": document.kind,
                    "service": document.service,
                    "environment": document.environment,
                    "checksum": checksum,
                    "document": serialized,
                    "updated_at": now().isoformat(),
                },
            )
            for identity, part, vector in pieces:
                expression = "CAST(:embedding AS vector)" if self.postgres else ":embedding"
                tx.conn.execute(
                    text(
                        f"INSERT INTO aegis_knowledge_chunks (id,document_id,service,environment,embedding_model,content,embedding) VALUES (:id,:document_id,:service,:environment,:model,:content,{expression})"
                    ),
                    {
                        "id": identity,
                        "document_id": document.id,
                        "service": document.service,
                        "environment": document.environment,
                        "model": EMBEDDING,
                        "content": part,
                        "embedding": vector,
                    },
                )
        return True

    def list_documents(
        self, *, kind: str | None = None, service: str, environment: str
    ) -> list[dict[str, Any]]:
        kind_filter = " AND kind=:kind" if kind is not None else ""
        with self.repo.transaction() as tx:
            rows = (
                tx.conn.execute(
                    text(
                        f"SELECT document FROM aegis_knowledge_documents WHERE (service=:service OR service='*') AND (environment=:environment OR environment='*'){kind_filter} ORDER BY id LIMIT 500"
                    ),
                    {"service": service, "environment": environment, "kind": kind},
                )
                .scalars()
                .all()
            )
        return [json.loads(str(row)) for row in rows]

    def delete_document(self, identity: str) -> None:
        with self.repo.transaction() as tx:
            tx.conn.execute(
                text("DELETE FROM aegis_knowledge_chunks WHERE document_id=:id"), {"id": identity}
            )
            tx.conn.execute(
                text("DELETE FROM aegis_knowledge_documents WHERE id=:id"), {"id": identity}
            )

    def counts(self) -> dict[str, Any]:
        with self.repo.transaction() as tx:
            documents = tx.conn.execute(
                text("SELECT count(*) FROM aegis_knowledge_documents")
            ).scalar_one()
            chunks_count = tx.conn.execute(
                text("SELECT count(*) FROM aegis_knowledge_chunks")
            ).scalar_one()
            version = (
                tx.conn.execute(
                    text("SELECT extversion FROM pg_extension WHERE extname='vector'")
                ).scalar_one()
                if self.postgres
                else None
            )
        return {"documents": documents, "chunks": chunks_count, "pgvector_version": version}

    def get_document(
        self, identity: str, *, service: str, environment: str
    ) -> dict[str, Any] | None:
        with self.repo.transaction() as tx:
            row = tx.conn.execute(
                text(
                    "SELECT document FROM aegis_knowledge_documents WHERE id=:id AND (service=:service OR service='*') AND (environment=:environment OR environment='*')"
                ),
                {"id": identity, "service": service, "environment": environment},
            ).scalar_one_or_none()
        return dict(json.loads(str(row))) if row is not None else None

    def search(
        self, query: str, *, service: str, environment: str, limit: int = 5, kind: str | None = None
    ) -> list[dict[str, Any]]:
        if not 1 <= len(query) <= 2000 or not 1 <= limit <= 10:
            raise ValueError("Retrieval query or limit is outside bounds")
        vector = embed(query)
        if not any(vector):
            return []
        parameters: dict[str, Any] = {
            "service": service,
            "environment": environment,
            "model": EMBEDDING,
            "limit": limit,
            "query": json.dumps(vector),
        }
        scope = "(c.service=:service OR c.service='*') AND (c.environment=:environment OR c.environment='*') AND c.embedding_model=:model"
        if kind is not None:
            if kind not in {"runbook", "incident", "service", "failure_pattern"}:
                raise ValueError("Unknown knowledge kind")
            scope += " AND d.kind=:kind"
            parameters["kind"] = kind
        with self.repo.transaction() as tx:
            if self.postgres:
                rows = (
                    tx.conn.execute(
                        text(
                            f"SELECT c.id,c.document_id,c.content,d.document,d.checksum,d.updated_at,1-(c.embedding <=> CAST(:query AS vector)) AS score FROM aegis_knowledge_chunks c JOIN aegis_knowledge_documents d ON d.id=c.document_id WHERE {scope} ORDER BY c.embedding <=> CAST(:query AS vector),c.id LIMIT :limit"
                        ),
                        parameters,
                    )
                    .mappings()
                    .all()
                )
                ranked = [(float(row["score"]), row) for row in rows]
            else:
                rows = (
                    tx.conn.execute(
                        text(
                            f"SELECT c.id,c.document_id,c.content,c.embedding,d.document,d.checksum,d.updated_at FROM aegis_knowledge_chunks c JOIN aegis_knowledge_documents d ON d.id=c.document_id WHERE {scope} ORDER BY c.id LIMIT 2001"
                        ),
                        parameters,
                    )
                    .mappings()
                    .all()
                )
                if len(rows) > 2000:
                    raise ValueError("SQLite retrieval fallback exceeds its small-corpus limit")
                ranked = sorted(
                    (
                        (
                            math.fsum(
                                a * b
                                for a, b in zip(
                                    vector, json.loads(str(row["embedding"])), strict=True
                                )
                            ),
                            row,
                        )
                        for row in rows
                    ),
                    key=lambda pair: (-pair[0], str(pair[1]["id"])),
                )[:limit]
        result: list[dict[str, Any]] = []
        for score, row in ranked:
            if not math.isfinite(score) or score < 0.12:
                continue
            document = json.loads(str(row["document"]))
            result.append(
                {
                    "id": row["id"],
                    "document_id": row["document_id"],
                    "title": document["title"],
                    "kind": document["kind"],
                    "source": document["source"],
                    "document_checksum": row["checksum"],
                    "document_updated_at": row["updated_at"],
                    "content": row["content"],
                    "score": round(score, 6),
                    "retrieval_backend": self.backend,
                    "embedding_model": EMBEDDING,
                }
            )
        return result
