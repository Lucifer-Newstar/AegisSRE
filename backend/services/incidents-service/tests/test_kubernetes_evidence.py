from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from incidents_service.config import Settings
from incidents_service.kubernetes_evidence import KubernetesEvidence
from incidents_service.models import now

NS = "aegissre-demo"


def config(tmp_path: Path) -> Settings:
    token = tmp_path / "projected-token"
    token.write_text("synthetic-fixture-token-one")
    return Settings(
        api_token="fixture",
        worker_enabled=True,
        redis_url="redis://unused-fixture",
        kube_evidence_enabled=True,
        kube_api_url="https://cluster.invalid",
        kube_token_path=str(token),
    )


def resource(
    identity: str, owner: str | None = None, *, service: str = "catalog-service"
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "uid": identity,
        "namespace": NS,
        "labels": {"app.kubernetes.io/name": service, "app.kubernetes.io/part-of": "aegisshop"},
    }
    if owner:
        metadata["ownerReferences"] = [{"uid": owner, "controller": True}]
    return {"metadata": metadata}


def responses() -> dict[str, list[dict[str, Any]]]:
    return {
        "deployments": [resource("deployment-uid")],
        "replicasets": [resource("replicaset-uid", "deployment-uid")],
        "pods": [resource("pod-uid", "replicaset-uid")],
        "events": [
            {
                "metadata": {"uid": "event-uid", "namespace": NS},
                "regarding": {
                    "kind": "Pod",
                    "name": "catalog-random-suffix",
                    "namespace": NS,
                    "uid": "pod-uid",
                },
                "reason": "BackOff",
                "note": "Back-off restarting failed container",
                "type": "Warning",
                "eventTime": now().isoformat(),
                "series": None,
            }
        ],
    }


def test_disabled_reader_never_opens_files_or_constructs_client() -> None:
    source = KubernetesEvidence(Settings(dev_mode=True))
    assert source.client is None
    assert asyncio.run(source.collect()) == []
    assert source.snapshot()["health_verdict"] == "unknown"
    assert source.checked_at is None


def test_uid_ownership_namespaced_readonly_requests_and_token_rotation(tmp_path: Path) -> None:
    settings = config(tmp_path)
    fixtures = responses()
    observed: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        assert request.method == "GET"
        assert request.url.host == "cluster.invalid"
        assert "/namespaces/" + NS + "/" in request.url.path
        assert request.url.params["limit"] == "100"
        kind = request.url.path.rsplit("/", 1)[-1]
        if kind != "events":
            assert "catalog-service" in request.url.params["labelSelector"]
        return httpx.Response(200, json={"metadata": {}, "items": fixtures[kind]})

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            source = KubernetesEvidence(settings, client)
            first = await source.collect()
            assert source.error is None and len(first) == 1
            assert first[0].payload["reason"] == "BackOff"
            assert first[0].service == "catalog-service"
            assert first[0].source == "k8s" and first[0].type == "k8s_event"
            Path(settings.kube_token_path).write_text("synthetic-fixture-token-two")
            second = await source.collect()
            assert second[0].id == first[0].id
            assert source.snapshot()["health_verdict"] == "unknown"
            assert "synthetic-fixture" not in json.dumps(source.snapshot())

    asyncio.run(exercise())
    assert len(observed) == 8
    assert all(row.headers["Authorization"].endswith("token-one") for row in observed[:4])
    assert all(row.headers["Authorization"].endswith("token-two") for row in observed[4:])


@pytest.mark.parametrize(
    "scenario",
    [
        "wrong_namespace",
        "pagination",
        "redirect",
        "unauthorized",
        "compressed",
        "oversized",
        "throttled",
    ],
)
def test_incomplete_or_unsafe_cluster_reads_report_unknown_not_success(
    tmp_path: Path, scenario: str
) -> None:
    settings = config(tmp_path)
    fixtures = responses()
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if scenario == "redirect":
            return httpx.Response(302, headers={"Location": "https://outside.invalid/"})
        if scenario == "throttled":
            return httpx.Response(429)
        if scenario == "unauthorized":
            return httpx.Response(401, text="private server output must not leak")
        if scenario == "compressed":
            return httpx.Response(200, content=b"", headers={"Content-Encoding": "gzip"})
        if scenario == "oversized":
            return httpx.Response(200, content=b"x" * 1_000_001)
        rows = fixtures[request.url.path.rsplit("/", 1)[-1]]
        if scenario == "wrong_namespace":
            rows[0]["metadata"]["namespace"] = "other-namespace"
        return httpx.Response(
            200,
            json={
                "metadata": {"continue": "more" if scenario == "pagination" else ""},
                "items": rows,
            },
        )

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            source = KubernetesEvidence(settings, client)
            assert await source.collect() == []
            assert source.error
            assert source.succeeded_at is None
            assert "private server output" not in json.dumps(source.snapshot())
            assert source.snapshot()["health_verdict"] == "unknown"

    asyncio.run(exercise())
    assert calls == (8 if scenario == "pagination" else 4)


def test_unowned_or_recreated_object_is_not_attributed_by_name(tmp_path: Path) -> None:
    settings = config(tmp_path)
    fixtures = responses()
    fixtures["events"][0]["regarding"]["uid"] = "old-pod-same-name"

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"items": fixtures[request.url.path.rsplit("/", 1)[-1]], "metadata": {}}
        )

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            source = KubernetesEvidence(settings, client)
            assert await source.collect() == []
            assert source.error is None and source.ignored == 1

    asyncio.run(exercise())


def test_background_stages_evidence_and_exposes_authenticated_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from threading import Event
    from types import SimpleNamespace

    import incidents_service.main as main
    from fastapi.testclient import TestClient
    from incidents_service.repository import Repository

    settings = config(tmp_path)
    fixtures = responses()
    staged = Event()
    records: list[Any] = []

    def stage(record: Any) -> None:
        records.append(record)
        staged.set()

    runtime = SimpleNamespace(
        delivery=SimpleNamespace(stage=stage),
        tick=lambda: None,
        close=lambda: None,
        ready=lambda: True,
        snapshot=lambda: {"enabled": True},
    )
    monkeypatch.setattr(main, "Runtime", lambda loop: runtime)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"metadata": {}, "items": fixtures[request.url.path.rsplit("/", 1)[-1]]}
            )
        )
    )
    source = KubernetesEvidence(settings, client)
    repo = Repository("sqlite:///:memory:")
    with TestClient(main.create_app(settings, repo, kube_source=source)) as http:
        assert staged.wait(5)
        assert http.get("/runtime").status_code == 401
        http.headers["Authorization"] = "Bearer fixture"
        status = http.get("/runtime").json()["kubernetes"]
        assert status["enabled"] and status["events"] == 1
        assert status["health_verdict"] == "unknown"
        assert http.get("/ready").status_code == 200
        source.error = "cluster_throttled"
        assert http.get("/ready").status_code == 503
    assert len(records) == 1 and records[0].source == "k8s"
    asyncio.run(client.aclose())
    repo.close()


def test_cluster_reads_require_explicit_https_origin_and_delivery_worker() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="HTTPS"):
        Settings(
            dev_mode=True,
            worker_enabled=True,
            redis_url="redis://unused",
            kube_evidence_enabled=True,
            kube_api_url="http://cluster.invalid",
        )
    with pytest.raises(ValidationError, match="delivery worker"):
        Settings(dev_mode=True, kube_evidence_enabled=True, kube_api_url="https://cluster.invalid")


@pytest.mark.parametrize("token", ["invalid token", "x" * 16385], ids=["invalid", "oversized"])
def test_invalid_projected_token_never_leaves_the_process(tmp_path: Path, token: str) -> None:
    settings = config(tmp_path)
    Path(settings.kube_token_path).write_text(token)

    def respond(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Invalid credentials must not be sent")

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            source = KubernetesEvidence(settings, client)
            assert await source.collect() == []
            assert source.error == "invalid_projected_token"

    asyncio.run(exercise())


@pytest.mark.parametrize("token,dev", [("", True), ("fixture", True), ("", False)])
def test_cluster_credentials_cannot_enable_unauthenticated_or_dev_mode(
    token: str, dev: bool
) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="authenticated non-dev"):
        Settings(
            api_token=token,
            dev_mode=dev,
            worker_enabled=True,
            redis_url="redis://unused",
            kube_evidence_enabled=True,
            kube_api_url="https://cluster.invalid",
        )


def test_throttle_is_not_hidden_by_another_concurrent_failure(tmp_path: Path) -> None:
    settings = config(tmp_path)

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/events"):
            return httpx.Response(429)
        return httpx.Response(200, json={"items": [{"metadata": {"namespace": "wrong"}}]})

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            source = KubernetesEvidence(settings, client)
            assert await source.collect() == []
            assert source.error == "cluster_throttled"

    asyncio.run(exercise())


def test_paginated_events_are_complete_before_ownership_attribution(tmp_path: Path) -> None:
    settings = config(tmp_path)
    fixtures = responses()
    observed = []

    def respond(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        kind = request.url.path.rsplit("/", 1)[-1]
        if kind == "events" and "continue" not in request.url.params:
            return httpx.Response(200, json={"metadata": {"continue": "opaque-next"}, "items": []})
        if kind == "events":
            assert request.url.params["continue"] == "opaque-next"
        return httpx.Response(200, json={"metadata": {}, "items": fixtures[kind]})

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            source = KubernetesEvidence(settings, client)
            result = await source.collect()
            assert source.error is None and len(result) == 1
            assert result[0].payload["object_uid"] == "pod-uid"

    asyncio.run(exercise())
    assert len(observed) == 5


@pytest.mark.parametrize("unfinished", [False, True])
def test_cluster_pagination_has_a_total_five_page_bound(tmp_path: Path, unfinished: bool) -> None:
    settings = config(tmp_path)
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        index = int(request.url.params.get("continue", "0"))
        continuation = str(index + 1) if index < 4 or unfinished else ""
        return httpx.Response(
            200,
            json={
                "metadata": {"continue": continuation},
                "items": [resource(str(index * 100 + i)) for i in range(100)],
            },
        )

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            source = KubernetesEvidence(settings, client)
            if unfinished:
                with pytest.raises(RuntimeError, match="cluster_list_truncated"):
                    await source._get("/api/v1/namespaces/" + NS + "/pods")
            else:
                assert len(await source._get("/api/v1/namespaces/" + NS + "/pods")) == 500

    asyncio.run(exercise())
    assert calls == 5


def test_cluster_page_bytes_share_one_response_budget(tmp_path: Path) -> None:
    settings = config(tmp_path)
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        item = resource(str(calls))
        item["padding"] = "x" * 600000
        return httpx.Response(200, json={"metadata": {"continue": str(calls)}, "items": [item]})

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            source = KubernetesEvidence(settings, client)
            with pytest.raises(RuntimeError, match="cluster_response_exceeds_bound"):
                await source._get("/api/v1/namespaces/" + NS + "/pods")

    asyncio.run(exercise())
    assert calls == 2
