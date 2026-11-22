#!/usr/bin/env python3
"""Run only in the disposable CI reader Job, never against an existing cluster.

This checks actual API/TLS/projected credentials and a genuine container crash,
not ten-fault accuracy or remediation. It never logs a credential/response body.
"""

from __future__ import annotations

import asyncio
import json
import os
import time

from eventbus import EventBus
from incidents_service.config import Settings
from incidents_service.delivery import DeliveryWorker
from incidents_service.engine import ReliabilityLoop
from incidents_service.kubernetes_evidence import KubernetesEvidence
from incidents_service.models import Event
from incidents_service.repository import Repository


async def main() -> None:
    if os.environ.get("AEGIS_ISOLATED_KIND_FIXTURE") != "true":
        raise RuntimeError("This driver is only for the explicitly isolated CI fixture")
    host = os.environ["KUBERNETES_SERVICE_HOST"]
    if ":" in host:
        host = "[" + host + "]"
    origin = "https://" + host + ":" + os.environ.get("KUBERNETES_SERVICE_PORT_HTTPS", "443")
    settings = Settings(
        api_token="disposable-kind-fixture-not-a-deployment-credential",
        database_url="sqlite:////tmp/kind-reader-proof.db",
        worker_enabled=True,
        redis_url="redis://127.0.0.1:1/0",
        kube_evidence_enabled=True,
        kube_api_url=origin,
        kube_namespace="aegissre-demo",
        allowed_targets=["catalog-service"],
        environment="kind-ci",
    )
    source = KubernetesEvidence(settings)
    selected = None
    try:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            records = await source.collect()
            if source.error:
                raise AssertionError("Real API reader failed: " + source.error)
            selected = next(
                (
                    item
                    for item in records
                    if item.service == "catalog-service"
                    and item.payload.get("object_kind") == "Pod"
                    and item.payload.get("event_type") == "Warning"
                    and "back" in str(item.payload.get("reason", "")).lower()
                ),
                None,
            )
            if selected is not None:
                break
            await asyncio.sleep(5)
        if selected is None:
            raise AssertionError(
                "No real crash/backoff event captured: " + json.dumps(source.snapshot())
            )
        assert selected.environment == "kind-ci" and selected.source == "k8s"
        assert (
            selected.payload["object_uid"]
            and selected.payload["namespace"] == settings.kube_namespace
        )
        pods = await source._get(f"/api/v1/namespaces/{settings.kube_namespace}/pods")
        assert any(
            pod.get("metadata", {}).get("uid") == selected.payload["object_uid"]
            and status.get("name") == "crash-fixture"
            and status.get("restartCount", 0) >= 1
            and status.get("lastState", {}).get("terminated", {}).get("exitCode") == 42
            for pod in pods
            for status in pod.get("status", {}).get("containerStatuses", [])
        ), "Expected actual fixture process exit 42 with a restart"
        assert source.client is not None
        # Same actual projected token, TLS session and explicit server origin.
        token = await asyncio.to_thread(source._token)
        headers = {"Authorization": "Bearer " + token}
        probes = [
            ("GET", f"/api/v1/namespaces/{settings.kube_namespace}/secrets?limit=1", None),
            ("GET", "/api/v1/namespaces/kube-system/pods?limit=1", None),
            (
                "POST",
                f"/apis/apps/v1/namespaces/{settings.kube_namespace}/deployments?dryRun=All",
                {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "metadata": {"name": "forbidden-dry-run-probe"},
                    "spec": {
                        "replicas": 0,
                        "selector": {"matchLabels": {"app": "probe"}},
                        "template": {
                            "metadata": {"labels": {"app": "probe"}},
                            "spec": {
                                "securityContext": {
                                    "runAsNonRoot": True,
                                    "runAsUser": 10001,
                                    "seccompProfile": {"type": "RuntimeDefault"},
                                },
                                "containers": [
                                    {
                                        "name": "probe",
                                        "image": "aegissre/evidence:ci",
                                        "securityContext": {
                                            "allowPrivilegeEscalation": False,
                                            "capabilities": {"drop": ["ALL"]},
                                        },
                                    }
                                ],
                            },
                        },
                    },
                },
            ),
        ]
        for method, path, body in probes:
            async with source.client.stream(
                method, origin + path, headers=headers, json=body, timeout=5, follow_redirects=False
            ) as response:
                assert response.status_code == 403, (
                    "Expected namespace/read-only denial, got HTTP " + str(response.status_code)
                )
                error = bytearray()
                async for chunk in response.aiter_bytes():
                    error.extend(chunk)
                    if len(error) > 16384:
                        raise AssertionError("Unexpected oversized denial")
                status_body = json.loads(error)
                verb = "create" if method == "POST" else "list"
                assert status_body.get("reason") == "Forbidden"
                assert "cannot " + verb + " resource" in status_body.get("message", ""), (
                    "Denial must come from RBAC, not admission or Pod Security"
                )
        repo = Repository(settings.database_url)
        bus = EventBus(settings.redis_url)
        try:
            worker = DeliveryWorker(ReliabilityLoop(repo, settings), bus)
            worker.stage(selected)
            worker.stage(selected)
            with repo.transaction() as tx:
                pending = [row for _, row in tx.pending() if row["id"] == selected.id]
                assert len(pending) == 1
                assert Event.model_validate(pending[0]).service == "catalog-service"
        finally:
            bus.close()
            repo.close()
        reopened = Repository(settings.database_url)
        try:
            with reopened.transaction() as tx:
                persisted = tx.queued_event(selected.id)
                assert persisted is not None and persisted["source"] == "k8s"
        finally:
            reopened.close()
        # Metadata only. Do not print a token, CA, event note or API error body.
        print(
            json.dumps(
                {
                    "result": "passed",
                    "real_api": True,
                    "verified_tls": True,
                    "projected_service_account": True,
                    "service": selected.service,
                    "source": selected.source,
                    "object_uid": selected.payload["object_uid"],
                    "event_reason": selected.payload["reason"],
                    "namespace_secret_write_denials": True,
                    "durable_sql_staging_reopen": True,
                    "redis_dispatch_tested_here": False,
                    "inference_invoked": False,
                    "remediation_executed": False,
                }
            )
        )
    finally:
        await source.close()


if __name__ == "__main__":
    asyncio.run(main())
