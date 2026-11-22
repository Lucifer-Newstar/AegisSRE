"""Durable DI-1 deployment history. No invented deployment seeds."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from aegis_storage import DocumentStore


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class DeploymentRecord:
    event_id: str
    service: str
    revision: str
    status: str
    envelope: dict[str, Any]
    stored_at: datetime = field(default_factory=_now)

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "service": self.service,
            "revision": self.revision,
            "status": self.status,
            "envelope": self.envelope,
            "stored_at": self.stored_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, body: dict[str, Any]) -> DeploymentRecord:
        values = dict(body)
        values["stored_at"] = datetime.fromisoformat(str(values["stored_at"]))
        return cls(**values)


class DeploymentStore:
    def __init__(self, url: str | None = None) -> None:
        from deployments_service.config import settings

        self.documents = DocumentStore("deployments", url or settings.database_url)
        self.seed_startup_deploys()

    def seed_startup_deploys(self) -> None:
        """Only record this process's real, explicitly supplied running revision."""
        from deployments_service.config import settings

        if not settings.deployment_revision:
            return
        service, revision = settings.service_name, settings.deployment_revision
        envelope = {
            "id": f"startup-{service}-{revision}",
            "schema_version": "0.2",
            "source": "deployment",
            "type": "deployment",
            "service": service,
            "environment": settings.environment,
            "timestamp": _now().isoformat(),
            "payload": {
                "action": "deploy",
                "revision": revision,
                "triggered_by": "platform",
                "status": "succeeded",
            },
        }
        record = DeploymentRecord(
            event_id=str(envelope["id"]),
            service=service,
            revision=revision,
            status="succeeded",
            envelope=envelope,
        )
        self.documents.put(record.event_id, record.as_dict(), if_absent=True)

    def reset(self) -> None:
        self.documents.clear()

    def get(self, event_id: str) -> DeploymentRecord | None:
        body = self.documents.get(event_id)
        return DeploymentRecord.from_dict(body) if body else None

    def put(self, record: DeploymentRecord) -> tuple[DeploymentRecord, bool]:
        body, created = self.documents.put(record.event_id, record.as_dict(), if_absent=True)
        existing = DeploymentRecord.from_dict(body)
        if existing.envelope != record.envelope:
            raise ValueError("Deployment event id already exists with different content")
        return existing, created

    def list(
        self, service: str | None = None, status: str | None = None, limit: int = 50
    ) -> list[DeploymentRecord]:
        records = [DeploymentRecord.from_dict(body) for body in self.documents.list()]
        records = [
            record
            for record in records
            if (not service or record.service == service)
            and (not status or record.status == status)
        ]
        records.sort(
            key=lambda record: (
                datetime.fromisoformat(str(record.envelope["timestamp"]).replace("Z", "+00:00")),
                record.stored_at,
            ),
            reverse=True,
        )
        return records[: max(0, min(limit, 500))]

    def latest(self, service: str) -> DeploymentRecord | None:
        records = self.list(service=service, limit=1)
        return records[0] if records else None


store = DeploymentStore()
