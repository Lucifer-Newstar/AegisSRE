"""Bounded read-only in-cluster Kubernetes evidence, off unless configured.

Sources: https://kubernetes.io/docs/reference/kubernetes-api/events/event-v1/
https://kubernetes.io/docs/tasks/run-application/access-api-from-pod/
Events are best-effort supplemental evidence, never a service health verdict.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import ssl
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from telemetry import EventEnvelope

from incidents_service.config import Settings
from incidents_service.models import now


class KubernetesEvidenceError(RuntimeError):
    """Safe diagnostic code, never a response, token or certificate body."""


class KubernetesEvidence:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.config, self.client, self.owned = settings, client, client is None
        self.error: str | None = None
        self.checked_at: datetime | None = None
        self.succeeded_at: datetime | None = None
        self.ignored = 0
        self.count = 0
        self.selector = (
            "app.kubernetes.io/part-of=aegisshop,app.kubernetes.io/name in ("
            + ",".join(settings.allowed_targets)
            + ")"
        )

    def _token(self) -> str:
        with Path(self.config.kube_token_path).open("rb") as stream:
            raw = stream.read(16385)
        if len(raw) > 16384:
            raise KubernetesEvidenceError("invalid_projected_token")
        value = raw.strip()
        if not value or len(value) > 16384 or re.fullmatch(rb"[A-Za-z0-9._~+/=-]+", value) is None:
            raise KubernetesEvidenceError("invalid_projected_token")
        return value.decode("ascii")

    async def _get(self, path: str, *, selected: bool = True) -> list[dict[str, Any]]:
        assert self.client is not None
        token = await asyncio.to_thread(self._token)
        params = {"limit": "100"}
        if selected:
            params["labelSelector"] = self.selector
        async with self.client.stream(
            "GET",
            self.config.kube_api_url.rstrip("/") + path,
            params=params,
            headers={
                "Authorization": "Bearer " + token,
                "Accept": "application/json",
                "Accept-Encoding": "identity",
            },
            follow_redirects=False,
            timeout=3,
        ) as response:
            response.raise_for_status()
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                raise KubernetesEvidenceError("unsupported_cluster_encoding")
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > 1_000_000:
                    raise KubernetesEvidenceError("cluster_response_exceeds_bound")
        document = json.loads(data)
        if not isinstance(document, dict) or not isinstance(document.get("items"), list):
            raise KubernetesEvidenceError("invalid_cluster_list")
        if document.get("metadata", {}).get("continue") or len(document["items"]) > 100:
            raise KubernetesEvidenceError("cluster_list_truncated")
        rows = document["items"]
        for row in rows:
            if (
                not isinstance(row, dict)
                or row.get("metadata", {}).get("namespace") != self.config.kube_namespace
            ):
                raise KubernetesEvidenceError("unexpected_cluster_namespace")
        return list(rows)

    def _identity(self, item: dict[str, Any]) -> tuple[str, str] | None:
        metadata = item.get("metadata", {})
        service = metadata.get("labels", {}).get("app.kubernetes.io/name")
        identity = metadata.get("uid")
        if (
            metadata.get("labels", {}).get("app.kubernetes.io/part-of") != "aegisshop"
            or service not in self.config.allowed_targets
            or not isinstance(identity, str)
            or not 1 <= len(identity) <= 128
        ):
            return None
        return identity, str(service)

    def _parse(self, resources: list[list[dict[str, Any]]], clock: datetime) -> list[EventEnvelope]:
        deployments, replicasets, pods, events = resources
        owners: dict[str, str] = {}
        for item in deployments:
            identity = self._identity(item)
            if identity:
                owners[identity[0]] = identity[1]
        for collection in (replicasets, pods):
            next_owners: dict[str, str] = {}
            for item in collection:
                identity = self._identity(item)
                references = item.get("metadata", {}).get("ownerReferences", [])
                if identity and any(
                    ref.get("controller") is True and owners.get(str(ref.get("uid"))) == identity[1]
                    for ref in references
                ):
                    next_owners[identity[0]] = identity[1]
            owners.update(next_owners)
        result: list[EventEnvelope] = []
        self.ignored = 0
        for item in events:
            regarding = item.get("regarding", {})
            service = owners.get(str(regarding.get("uid", "")))
            if service is None or regarding.get("namespace") != self.config.kube_namespace:
                self.ignored += 1
                continue
            series = item.get("series") or {}
            observed = (
                series.get("lastObservedTime")
                or item.get("eventTime")
                or item.get("deprecatedLastTimestamp")
            )
            if not isinstance(observed, str):
                self.ignored += 1
                continue
            timestamp = datetime.fromisoformat(observed.replace("Z", "+00:00"))
            if timestamp.tzinfo is None or not -60 <= (clock - timestamp).total_seconds() <= 1800:
                self.ignored += 1
                continue
            count = int(series.get("count", item.get("deprecatedCount", 1)))
            if not 1 <= count <= 2147483647:
                raise KubernetesEvidenceError("invalid_event_series_count")
            payload = {
                "namespace": self.config.kube_namespace,
                "object_kind": str(regarding.get("kind", ""))[:60],
                "object_name": str(regarding.get("name", ""))[:200],
                "object_uid": str(regarding["uid"]),
                "reason": str(item.get("reason", ""))[:128],
                "message": str(item.get("note", ""))[:1000],
                "event_type": str(item.get("type", ""))[:40],
                "reporting_controller": str(item.get("reportingController", ""))[:200],
                "series_count": count,
                "source_api": "events.k8s.io/v1",
                "best_effort": True,
            }
            serialized = json.dumps(
                [
                    item.get("metadata", {}).get("uid"),
                    service,
                    self.config.environment,
                    timestamp.isoformat(),
                    payload,
                ],
                sort_keys=True,
            )
            result.append(
                EventEnvelope(
                    id="k8s_" + hashlib.sha256(serialized.encode()).hexdigest(),
                    timestamp=timestamp,
                    source="k8s",
                    type="k8s_event",
                    service=service,
                    environment=self.config.environment,
                    severity="warning" if item.get("type") == "Warning" else "info",
                    payload=payload,
                )
            )
        return result

    async def collect(self) -> list[EventEnvelope]:
        if not self.config.kube_evidence_enabled:
            return []
        self.checked_at = now()
        try:
            if self.client is None:
                context = await asyncio.to_thread(
                    ssl.create_default_context, cafile=self.config.kube_ca_path
                )
                self.client = httpx.AsyncClient(
                    verify=context, trust_env=False, follow_redirects=False
                )
            namespace = self.config.kube_namespace
            paths = [
                f"/apis/apps/v1/namespaces/{namespace}/deployments",
                f"/apis/apps/v1/namespaces/{namespace}/replicasets",
                f"/api/v1/namespaces/{namespace}/pods",
                f"/apis/events.k8s.io/v1/namespaces/{namespace}/events",
            ]
            async with asyncio.timeout(10):
                responses = await asyncio.gather(
                    *(self._get(path, selected=index < 3) for index, path in enumerate(paths)),
                    return_exceptions=True,
                )
            # A concurrent parse failure must not hide throttling/access denial
            # from another request in the same bounded batch.
            for response in responses:
                if isinstance(
                    response, httpx.HTTPStatusError
                ) and response.response.status_code in {401, 403, 429}:
                    raise response
            resources: list[list[dict[str, Any]]] = []
            for response in responses:
                if isinstance(response, BaseException):
                    raise response
                resources.append(response)
            result = self._parse(resources, self.checked_at)
            self.error, self.succeeded_at, self.count = None, now(), len(result)
            return result
        except httpx.HTTPStatusError as exc:
            self.error = (
                "cluster_throttled"
                if exc.response.status_code == 429
                else "cluster_access_denied"
                if exc.response.status_code in {401, 403}
                else "cluster_read_failed"
            )
        except KubernetesEvidenceError as exc:
            self.error = str(exc)
        except (
            httpx.HTTPError,
            OSError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            RecursionError,
            TimeoutError,
        ):
            self.error = "cluster_read_failed"
        self.count = 0
        return []

    def snapshot(self) -> dict[str, Any]:
        return {
            "enabled": self.config.kube_evidence_enabled,
            "namespace": self.config.kube_namespace,
            "checked_at": self.checked_at.isoformat() if self.checked_at else None,
            "succeeded_at": self.succeeded_at.isoformat() if self.succeeded_at else None,
            "error": self.error,
            "events": self.count,
            "ignored_unmapped_or_stale": self.ignored,
            "health_verdict": "unknown",
            "note": "Read-only, bounded and best-effort. Missing events do not establish health. Deleted objects not present in the ownership snapshot cannot be attributed.",
        }

    async def close(self) -> None:
        if self.owned and self.client is not None:
            await self.client.aclose()
