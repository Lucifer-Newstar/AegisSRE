# Knowledge retrieval and runbooks

The reliability API can index packaged runbooks, known failure-pattern clues,
verified-closed incidents and selected service metadata. Retrieval is read-only.
The returned knowledge does not authorize a restart, rollback or any other action.
The policy engine remains the action boundary.

## Storage and embeddings

- Compose enables `AEGIS_KNOWLEDGE_ENABLED=true` and uses PostgreSQL 16 with
  pgvector 0.8.1, pinned by image digest. The application creates the extension
  and its own knowledge tables when enabled. On a managed database, have the
  database owner install the extension through the normal change process first.
- Search on PostgreSQL uses actual `vector(768)` storage and the pgvector cosine
  distance operator, with service/environment filters. This is exact search for
  the project's small corpus, not a claimed large-scale ANN deployment.
- The built-in embedding is deterministic local word/bigram lexical hashing.
  It is **not a neural embedding model** and makes no semantic-model quality
  claim. No weights are downloaded and no paid inference is needed for indexing.
- SQLite uses an explicitly named `sqlite_exact_cosine` development/test fallback,
  capped at 2,000 candidate chunks. It is never reported as pgvector acceptance.
- Documents are chunked with overlap. Citations include source, document ID,
  content checksum, indexed time, embedding version and a versioned chunk ID.
  Updates replace old chunks atomically. Returned snippets preserve the content
  used for that retrieval; a later document update must not be mistaken for the
  earlier cited version.

## Existing PostgreSQL volumes

The earlier Compose image was PostgreSQL 16 on Alpine. The pgvector image uses
Debian. Do not blindly reuse an existing Alpine database volume with a different
base image. Back up an existing database first, restore a logical dump into a
separate pgvector-enabled PostgreSQL 16 instance, and validate row counts and
application behavior before switching. Keep the original volume intact until the
migration has been checked. Do not delete a database volume to fix an extension
error. Fresh disposable CI stacks need no data migration.

No existing user database is migrated by this code change. For a custom database,
keep the existing image until a supported pgvector installation/migration is
ready. Leave knowledge indexing disabled if the extension is not yet available.

## Indexing and freshness

The package contains ten investigation/recovery runbooks, one per approved fault
label. Pattern documents describe heuristic clues, not confirmed root causes.
The indexer loads those documents at startup and refreshes selected registry
metadata and closed incidents every 60 seconds on its own background task.
Indexing does not hold a SQL transaction during network I/O or embedding work.
Unchanged documents are not reindexed. Deleted registry services and removed
packaged runbooks are removed from retrieval.

The configured registry origin belongs to the deployment environment. Only
allowed service IDs are indexed. Registry URLs and heartbeat noise are excluded.
Closed-incident documents preserve the uncertainty of the original analysis and
label simulation outcomes explicitly. Verified recovery is not proof of cause.
Open incidents are not presented as resolved historical cases.

`GET /knowledge/status` reports the backend, actual extension version, corpus
counts, refresh time and failures. Check those fields when using metadata or
historical context. A failed refresh is not evidence that a service is healthy.

## Authenticated API

Through the gateway, prefix these paths with `/api/v1`:

- `GET /runbooks`: scoped list, without full content.
- `GET /runbooks/{runbook_id}`: the full runbook. Both the slug and its
  `runbook:`-prefixed document ID are accepted.
- `POST /knowledge/search`: body has `query`, an allowed `service`, optional
  `limit` (1–10) and optional `kind` (`runbook`, `incident`, `service`,
  `failure_pattern`). The environment comes from trusted configuration.
- `GET /incidents/{incident_id}/context`: cited retrieved context alongside the
  incident's evidence IDs. Snapshot reads finish before retrieval starts.
- `GET /knowledge/status`: feature status and indexing diagnostics.

These endpoints expose no document-upload, shell, executor or arbitrary-URL tool.
All use the existing bearer-authenticated API boundary. A disabled knowledge
feature returns an explicit unavailable response, not sample results.

## Validation and limits

Local unit tests cover isolation, idempotency, chunk replacement, stale metadata
removal, prior-incident uncertainty, auth and a small authored ten-query retrieval
regression with a recall@5 threshold of 0.8. This is a regression corpus, not the
real chaos evaluation or a blind human benchmark.

The actual PostgreSQL integration test verifies the extension, the stored vector
type/dimensions, cosine distance and persistence across reopening the repository.
The hosted Compose driver `scripts/check_knowledge_stack.py` verifies actual
pgvector-backed retrieval, packaged runbook content/citations and gateway auth.
Those hosted checks must pass before merging this milestone.

LLM-assisted analysis, Ask Aegis, the runbook console viewer and retrieval quality
on real evaluation faults are separate remaining work. Nothing here claims that
the full platform or its accuracy targets are finished.
