from __future__ import annotations

import asyncio
from typing import Any

import pytest
from aegis_security import ServiceAuth
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.types import Message, Scope

TOKEN = "disposable-service-fixture"


def client(*, token: str = TOKEN, dev_mode: bool = False) -> TestClient:
    app = FastAPI()
    app.add_middleware(
        ServiceAuth,
        token=token,
        read_token="disposable-read-fixture" if token else "",
        dev_mode=dev_mode,
    )

    @app.get("/health")
    @app.get("/metrics")
    @app.get("/ready")
    @app.get("/services")
    def read() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/echo")
    async def echo(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    return TestClient(app)


@pytest.mark.parametrize("path", ["/ready", "/services", "/docs", "/openapi.json", "/"])
def test_all_non_probe_routes_require_service_token(path: str) -> None:
    with client() as http:
        response = http.get(path)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert TOKEN not in response.text


def test_health_and_metrics_are_public_but_data_uses_constant_credential() -> None:
    with client() as http:
        assert http.get("/health").status_code == 200
        assert http.get("/metrics").status_code == 200
        assert (
            http.get("/services", headers={"Authorization": "Bearer " + TOKEN}).status_code == 200
        )
        assert http.get("/services", headers={"Authorization": "Bearer wrong"}).status_code == 401
        duplicate = [("Authorization", "Bearer " + TOKEN), ("Authorization", "Bearer wrong")]
        assert http.get("/services", headers=duplicate).status_code == 401


def test_chunked_writes_are_bounded_and_valid_bodies_are_replayed_once() -> None:
    with client() as http:
        headers = {"Authorization": "Bearer " + TOKEN}
        assert http.post("/echo", content=b"ok", headers=headers).json() == {"size": 2}
        response = http.post("/echo", content=iter([b"a" * 32768] * 3), headers=headers)
        assert response.status_code == 413


def test_dev_mode_is_explicit_and_never_overrides_a_configured_token() -> None:
    with pytest.raises(ValueError, match="metadata API/read tokens"):
        ServiceAuth.validate("", False)
    with client(token="", dev_mode=True) as http:
        assert http.get("/services").status_code == 200
    with client(dev_mode=True) as http:
        assert http.get("/services").status_code == 401
    with pytest.raises(ValueError, match="format"):
        ServiceAuth.validate("contains whitespace", False, "disposable-read-fixture")


async def _reject_without_reading() -> None:
    sent: list[Message] = []

    async def never_receive() -> Message:
        raise AssertionError("Unauthenticated body must not be consumed")

    async def never_app(scope: Scope, receive: Any, send: Any) -> None:
        raise AssertionError("Unauthenticated request must not reach application")

    async def send(message: Message) -> None:
        sent.append(message)

    scope: Scope = {"type": "http", "method": "POST", "path": "/echo", "headers": []}
    await ServiceAuth(never_app, TOKEN, read_token="disposable-read-fixture")(
        scope, never_receive, send
    )
    assert sent[0]["type"] == "http.response.start" and sent[0]["status"] == 401


def test_unauthorized_request_is_rejected_before_reading_body() -> None:
    asyncio.run(_reject_without_reading())


def test_read_credential_cannot_write() -> None:
    with client() as http:
        headers = {"Authorization": "Bearer disposable-read-fixture"}
        assert http.get("/services", headers=headers).status_code == 200
        assert http.post("/echo", content=b"not accepted", headers=headers).status_code == 403
    with pytest.raises(ValueError, match="distinct"):
        ServiceAuth.validate(TOKEN, False, TOKEN)


def test_websockets_are_not_an_alternate_auth_path() -> None:
    from starlette.websockets import WebSocketDisconnect

    with client() as http:
        with pytest.raises(WebSocketDisconnect) as caught, http.websocket_connect("/services"):
            raise AssertionError("Metadata websocket must not open")
        assert caught.value.code == 1008
