"""Durable service catalogue and bounded live readiness probes."""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from aegis_storage import DocumentStore

HEARTBEAT_HEALTHY = timedelta(seconds=30)
HEARTBEAT_DEGRADED = timedelta(seconds=90)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class ServiceRecord:
    id: str
    name: str
    url: str
    version: str = "0.1.0"
    status: str = "unknown"
    owner: str = "unassigned"
    availability_slo: float = 0.999
    latency_slo_seconds: float = 1.0
    registered_at: datetime = field(default_factory=_now)
    last_heartbeat_at: datetime | None = None

    def probe_ready(self, timeout: float = 0.4) -> None:
        url = self.url.rstrip("/") + "/ready"

        # The host was validated against a configured allowlist at registration.
        # Redirects are forbidden so a registered service cannot redirect a probe
        # to a cloud metadata endpoint or another privileged local service.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(
                self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
            ) -> None:
                return None

        try:
            opener = urllib.request.build_opener(NoRedirect)
            with opener.open(url, timeout=timeout) as response:
                if 200 <= int(response.status) < 300:
                    self.status, self.last_heartbeat_at = "healthy", _now()
                    return
            self.status = "degraded"
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            self.status = "unhealthy"

    def refresh_status(self, current: datetime | None = None) -> None:
        if self.last_heartbeat_at is None:
            self.status = "unknown"
            return
        age = (current or _now()) - self.last_heartbeat_at
        self.status = (
            "healthy"
            if age <= HEARTBEAT_HEALTHY and self.last_heartbeat_at
            else "degraded"
            if age <= HEARTBEAT_DEGRADED
            else "unknown"
        )

    def as_dict(
        self, include_heartbeats: bool = True, *, skip_refresh: bool = False
    ) -> dict[str, Any]:
        if not skip_refresh:
            self.refresh_status()
        result: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "version": self.version,
            "status": self.status,
            "owner": self.owner,
            "availability_slo": self.availability_slo,
            "latency_slo_seconds": self.latency_slo_seconds,
            "registered_at": self.registered_at.isoformat(),
        }
        if include_heartbeats:
            result["last_heartbeat_at"] = (
                self.last_heartbeat_at.isoformat() if self.last_heartbeat_at else None
            )
        return result

    @classmethod
    def from_dict(cls, body: dict[str, Any]) -> ServiceRecord:
        values = dict(body)
        values["registered_at"] = datetime.fromisoformat(str(values["registered_at"]))
        values["last_heartbeat_at"] = (
            datetime.fromisoformat(str(values["last_heartbeat_at"]))
            if values.get("last_heartbeat_at")
            else None
        )
        return cls(**values)


class RegistryStore:
    def __init__(self, url: str | None = None) -> None:
        from registry_service.config import settings

        self.documents = DocumentStore("registry", url or settings.database_url)
        self._seed()

    def _seed(self) -> None:
        seeds = (
            ("catalog-service", "AegisShop Catalog", 9001),
            ("cart-service", "AegisShop Cart", 9002),
            ("order-service", "AegisShop Order", 9003),
            ("payment-service", "AegisShop Payment", 9004),
            ("registry-service", "AegisSRE Registry", 8101),
            ("deployments-service", "AegisSRE Deployments", 8701),
        )
        for service_id, name, port in seeds:
            record = ServiceRecord(id=service_id, name=name, url=f"http://{service_id}:{port}")
            self.documents.put(service_id, record.as_dict(skip_refresh=True), if_absent=True)

    def reset(self) -> None:
        self.documents.clear()
        self._seed()

    def refresh_all(self) -> None:
        from registry_service.config import settings

        for body in self.documents.list():
            if body.get("deleted"):
                continue
            record = ServiceRecord.from_dict(body)
            if settings.registry_probe:
                record.probe_ready()
            else:
                record.refresh_status()
            self._save_probe(record)

    def list(
        self, status: str | None = None, include_heartbeats: bool = True
    ) -> list[dict[str, Any]]:
        from registry_service.config import settings

        if settings.registry_probe:
            self.refresh_all()
        records = [
            ServiceRecord.from_dict(body)
            for body in self.documents.list()
            if not body.get("deleted")
        ]
        result = [
            record.as_dict(include_heartbeats, skip_refresh=settings.registry_probe)
            for record in records
        ]
        return sorted(
            [body for body in result if not status or body["status"] == status],
            key=lambda body: str(body["id"]),
        )

    def _save_probe(self, record: ServiceRecord) -> None:
        def apply(current: dict[str, Any] | None) -> dict[str, Any] | None:
            if current is None or current.get("deleted") or current.get("url") != record.url:
                return current
            return {
                **current,
                "status": record.status,
                "last_heartbeat_at": record.last_heartbeat_at.isoformat()
                if record.last_heartbeat_at
                else None,
            }

        self.documents.mutate(record.id, apply)

    def get(self, service_id: str) -> ServiceRecord | None:
        body = self.documents.get(service_id)
        if body is None or body.get("deleted"):
            return None
        from registry_service.config import settings

        record = ServiceRecord.from_dict(body)
        if settings.registry_probe:
            record.probe_ready()
            self._save_probe(record)
        else:
            record.refresh_status()
        return record

    def register(
        self,
        service_id: str,
        name: str,
        url: str,
        version: str = "0.1.0",
        *,
        owner: str = "unassigned",
        availability_slo: float = 0.999,
        latency_slo_seconds: float = 1.0,
    ) -> ServiceRecord:
        from registry_service.config import settings

        parsed = urlsplit(url)
        if (
            parsed.hostname not in settings.registry_allowed_hosts
            or parsed.username
            or parsed.password
        ):
            raise ValueError(
                "Service URL host is not in REGISTRY_ALLOWED_HOSTS, or includes credentials"
            )
        previous = self.documents.get(service_id)
        record = ServiceRecord(
            id=service_id,
            name=name,
            url=url,
            version=version,
            owner=owner,
            availability_slo=availability_slo,
            latency_slo_seconds=latency_slo_seconds,
        )
        if previous:
            record.registered_at = datetime.fromisoformat(str(previous["registered_at"]))
        self.documents.put(service_id, record.as_dict(skip_refresh=True))
        return record

    def heartbeat(self, service_id: str) -> ServiceRecord | None:
        def beat(body: dict[str, Any] | None) -> dict[str, Any] | None:
            if body is None or body.get("deleted"):
                return body
            return {**body, "last_heartbeat_at": _now().isoformat(), "status": "healthy"}

        result = self.documents.mutate(service_id, beat)
        return ServiceRecord.from_dict(result) if result and not result.get("deleted") else None

    def delete(self, service_id: str) -> bool:
        existed = False

        def remove(body: dict[str, Any] | None) -> dict[str, Any] | None:
            nonlocal existed
            existed = body is not None and not body.get("deleted", False)
            return {**body, "deleted": True} if body else None

        self.documents.mutate(service_id, remove)
        return existed


store = RegistryStore()
