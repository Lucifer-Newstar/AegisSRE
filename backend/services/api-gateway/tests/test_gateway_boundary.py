from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from typing import Any

import fakeredis
import httpx
import pytest
from api_gateway.config import Settings
from api_gateway.main import RateGate, create_app
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

AUTH = {"Authorization": "Bearer gateway-fixture"}


@pytest.fixture
def gateway() -> Iterator[tuple[TestClient, list[httpx.Request], Redis]]:
    observed: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(
            200,
            json={"status": "ready", "path": request.url.path},
            headers={"Set-Cookie": "upstream=never-share; Path=/"},
        )

    transport = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    redis = fakeredis.FakeRedis()
    app = create_app(
        Settings(api_token="gateway-fixture", incidents_token="backend-fixture"),
        http=transport,
        redis_client=redis,
    )
    with TestClient(app) as client:
        yield client, observed, redis
    assert not transport.cookies
    asyncio.run(transport.aclose())
    redis.close()


def test_authentication_precedes_body_and_all_business_routing(
    gateway: tuple[TestClient, list[httpx.Request], Redis],
) -> None:
    client, requests, _ = gateway
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/services").status_code == 401
    assert client.post("/api/v1/events", content=b"x" * 70000).status_code == 401
    assert client.get("/api/v1/audit", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert not requests
    assert client.get("/docs").status_code == 404


def test_proxy_has_fixed_origins_queries_and_correlation(
    gateway: tuple[TestClient, list[httpx.Request], Redis],
) -> None:
    client, requests, _ = gateway
    response = client.get(
        "/api/v1/services?status=healthy",
        headers={**AUTH, "X-Request-ID": "request-123", "Cookie": "private=do-not-forward"},
    )
    assert response.status_code == 200
    assert requests[-1].url.host == "127.0.0.1" and requests[-1].url.port == 8101
    assert requests[-1].url.path == "/services"
    assert requests[-1].url.params["status"] == "healthy"
    assert requests[-1].headers["x-request-id"] == "request-123"
    assert "cookie" not in requests[-1].headers and "authorization" not in requests[-1].headers
    assert response.headers["x-request-id"] == "request-123"
    assert response.headers["cache-control"] == "no-store"
    count = len(requests)
    for path in (
        "/api/v1/proxy/http://evil/private",
        "/api/v1/events/%2e%2e",
        "/api/v1/incidents/a/delete",
    ):
        assert client.post(path, headers=AUTH).status_code in {404, 405}
    assert client.get("/api/v1/services?url=http://evil", headers=AUTH).status_code == 422
    assert len(requests) == count


def test_internal_token_and_verified_actor_replace_caller_claims(
    gateway: tuple[TestClient, list[httpx.Request], Redis],
) -> None:
    client, requests, _ = gateway
    response = client.post(
        "/api/v1/incidents/inc_123/approve",
        headers=AUTH,
        json={"actor": "someone-else", "note": "approved"},
    )
    assert response.status_code == 200
    assert requests[-1].headers["authorization"] == "Bearer backend-fixture"
    assert json.loads(requests[-1].content)["actor"] == "token:operator"
    assert json.loads(requests[-1].content)["note"] == "approved"


def test_distributed_rate_window_is_atomic_and_not_sliding() -> None:
    redis = fakeredis.FakeRedis()
    first, second = RateGate(redis), RateGate(redis)
    assert first.consume("shared-principal", 2)[0]
    key = redis.keys()[0]
    redis.expire(key, 10)
    assert second.consume("shared-principal", 2)[0]
    allowed, retry = first.consume("shared-principal", 2)
    assert not allowed and 1 <= retry <= 10
    assert redis.ttl(key) <= 10


def test_redis_failure_closes_gateway(
    gateway: tuple[TestClient, list[httpx.Request], Redis], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, requests, redis = gateway

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise RedisConnectionError("lost dependency")

    monkeypatch.setattr(redis, "pipeline", fail)
    response = client.get("/api/v1/services", headers=AUTH)
    assert response.status_code == 503
    assert not requests


def test_body_limits_and_content_type_apply_to_reads_too(
    gateway: tuple[TestClient, list[httpx.Request], Redis],
) -> None:
    client, requests, _ = gateway
    assert (
        client.request("GET", "/api/v1/events", headers=AUTH, content=b"x" * 65537).status_code
        == 413
    )
    assert client.post("/api/v1/events", headers=AUTH, content=b"x" * 65537).status_code == 413
    assert client.post("/api/v1/events", headers=AUTH, content="not-json").status_code == 415
    assert client.post("/api/v1/events", headers=AUTH, json=[]).status_code == 422
    assert not requests


@pytest.mark.parametrize("kind", ["redirect", "oversized", "server_error", "connection"])
def test_upstream_failure_is_bounded_and_does_not_leak(kind: str) -> None:
    observed: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        if kind == "connection":
            raise httpx.ConnectError("private-internal-diagnostic", request=request)
        if kind == "redirect":
            return httpx.Response(302, headers={"Location": "http://evil/private"})
        if kind == "oversized":
            return httpx.Response(200, content=b"x" * (8 * 1024 * 1024 + 1))
        return httpx.Response(500, text="private-internal-diagnostic")

    transport = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    with TestClient(
        create_app(
            Settings(api_token="gateway-fixture", incidents_token="backend-fixture"),
            http=transport,
            redis_client=fakeredis.FakeRedis(),
        )
    ) as client:
        response = client.get("/api/v1/services", headers=AUTH)
        assert response.status_code == 502
        assert "private-internal-diagnostic" not in response.text
        assert len(observed) == 1
    asyncio.run(transport.aclose())


def test_ready_checks_all_fixed_upstreams_and_schema_is_secret_free(
    gateway: tuple[TestClient, list[httpx.Request], Redis],
) -> None:
    client, requests, _ = gateway
    assert client.get("/api/v1/ready", headers=AUTH).json() == {"status": "ready"}
    assert {request.url.port for request in requests} == {8101, 8701, 8201}
    assert all(request.url.path == "/ready" for request in requests)
    app = client.app
    assert isinstance(app, FastAPI)
    schema = app.openapi()
    assert "gateway-fixture" not in json.dumps(schema)
    assert schema["paths"]["/api/v1/services"]["get"]["security"] == [{"HTTPBearer": []}]


def test_gateway_rate_limit_response_and_failed_auth_are_independent(
    gateway: tuple[TestClient, list[httpx.Request], Redis],
) -> None:
    client, requests, redis = gateway
    # A failed-auth bucket cannot lock out a caller holding the actual key.
    for _ in range(31):
        response = client.get("/api/v1/services")
    assert response.status_code == 429 and int(response.headers["retry-after"]) > 0
    assert client.get("/api/v1/services", headers=AUTH).status_code == 200
    for key in redis.scan_iter():
        assert b"gateway-fixture" not in key and b"backend-fixture" not in key
    assert len(requests) == 1
