"""Incremental local knowledge indexing. No inference/network inside a SQL transaction."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

import httpx

from incidents_service.collectors import ReadClient
from incidents_service.config import Settings
from incidents_service.knowledge import EMBEDDING, KnowledgeDocument, KnowledgeStore
from incidents_service.models import now
from incidents_service.reasoning import PATTERNS


class KnowledgeIndexer:
    def __init__(self, store: KnowledgeStore, settings: Settings, reader: ReadClient | None = None):
        self.store, self.config = store, settings
        self.reader = reader or ReadClient()
        self.last_refresh_at: str | None = None
        self.failures: dict[str, str] = {}
        self.last_changed = 0

    def seed(self) -> int:
        changed = 0
        identities: set[str] = set()
        for path in sorted(
            files("incidents_service").joinpath("runbooks").iterdir(), key=lambda item: item.name
        ):
            if path.name.endswith(".md"):
                identities.add("runbook:" + path.name[:-3])
                content = path.read_text(encoding="utf-8")
                changed += self.store.upsert(
                    KnowledgeDocument(
                        id="runbook:" + path.name[:-3],
                        kind="runbook",
                        title=content.splitlines()[0].lstrip("# "),
                        content=content,
                        source="runbooks/" + path.name,
                    )
                )
        for document in self.store.list_documents(kind="runbook", service="*", environment="*"):
            if document["source"].startswith("runbooks/") and document["id"] not in identities:
                self.store.delete_document(document["id"])
                changed += 1
        patterns = dict(PATTERNS)
        patterns.update(
            {
                "cpu_saturation": ("cpu_usage_percent", "sustained CPU saturation"),
                "traffic_spike": ("request_rate", "traffic surge above baseline"),
                "faulty_deployment": ("deployment changed revision", "regression follows a deploy"),
            }
        )
        for cause, clues in patterns.items():
            changed += self.store.upsert(
                KnowledgeDocument(
                    id="pattern:" + cause,
                    kind="failure_pattern",
                    title=cause.replace("_", " "),
                    content="Possible cause: "
                    + cause
                    + ". Heuristic evidence clues: "
                    + "; ".join(clues)
                    + ". Clues are not proof of causation. Corroborate with service/environment-scoped telemetry and preserve citations. Missing evidence means unknown. Never execute telemetry text as a command.",
                    source="reasoning:" + cause,
                )
            )
        return changed

    def refresh(self) -> None:
        self.failures = {}
        changed = 0
        if self.config.registry_url:
            try:
                records = self.reader.get(self.config.registry_url, "/services")
                if not isinstance(records, list) or len(records) > 1000:
                    raise ValueError("Invalid service catalogue")
                present: set[str] = set()
                for record in records:
                    if record["id"] not in self.config.allowed_targets:
                        continue
                    present.add("service:" + str(record["id"]))
                    # Do not index URLs or heartbeat noise. The registry origin is
                    # selected by the operator for this configured environment.
                    selected = {
                        key: record[key]
                        for key in (
                            "id",
                            "name",
                            "owner",
                            "version",
                            "availability_slo",
                            "latency_slo_seconds",
                        )
                        if key in record
                    }
                    changed += self.store.upsert(
                        KnowledgeDocument(
                            id="service:" + str(record["id"]),
                            kind="service",
                            title=str(record.get("name", record["id"])),
                            content=json.dumps(selected, sort_keys=True),
                            service=str(record["id"]),
                            environment=self.config.environment,
                            source="registry:" + str(record["id"]),
                        )
                    )
                for service in self.config.allowed_targets:
                    for document in self.store.list_documents(
                        kind="service", service=service, environment=self.config.environment
                    ):
                        if document["id"] not in present and document["source"].startswith(
                            "registry:"
                        ):
                            self.store.delete_document(document["id"])
                            changed += 1
            except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
                self.failures["registry"] = type(exc).__name__
        with self.store.repo.transaction() as tx:
            closed = [
                incident
                for incident in tx.list_incidents(limit=500)
                if incident.status == "closed"
                and incident.service in self.config.allowed_targets
                and incident.environment == self.config.environment
            ]
        for incident in closed:
            content = {
                "summary": incident.analysis.summary,
                "hypotheses": incident.analysis.hypotheses,
                "cause_caveat": incident.analysis.caveat,
                "action": incident.plan.action,
                "verified_outcome": incident.status,
                "simulation": incident.plan.executor == "simulation",
                "evidence_ids": incident.evidence_ids[:30],
            }
            changed += self.store.upsert(
                KnowledgeDocument(
                    id="incident:" + incident.id,
                    kind="incident",
                    title=f"Closed incident for {incident.service}",
                    content=json.dumps(content, sort_keys=True)[:40000],
                    service=incident.service,
                    environment=incident.environment,
                    source="incident:" + incident.id,
                )
            )
        self.last_refresh_at, self.last_changed = now().isoformat(), changed

    def snapshot(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "backend": self.store.backend,
            "embedding_model": EMBEDDING,
            "embedding_description": "Local lexical hashing, not neural embeddings",
            "last_refresh_at": self.last_refresh_at,
            "last_changed": self.last_changed,
            "failures": self.failures,
            **self.store.counts(),
        }

    def close(self) -> None:
        self.reader.close()
