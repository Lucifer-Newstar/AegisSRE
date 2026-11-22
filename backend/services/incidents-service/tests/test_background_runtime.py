from __future__ import annotations

import time
from datetime import timedelta
from typing import Any

import fakeredis
import pytest
from fastapi.testclient import TestClient
from incidents_service.config import Settings
from incidents_service.main import create_app
from incidents_service.models import now
from incidents_service.repository import Repository
from telemetry import EventEnvelope


def test_background_delivery_is_live_and_stops_with_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("eventbus.eventbus.Redis.from_url", lambda *a, **k: fake)
    settings = Settings(api_token="runtime-test", worker_enabled=True, redis_url="redis://unused")
    app = create_app(settings, Repository("sqlite:///:memory:"))
    with TestClient(app) as client:
        assert client.get("/runtime").status_code == 401
        client.headers["Authorization"] = "Bearer runtime-test"
        runtime = app.state.runtime
        event = EventEnvelope(
            id="background-one",
            type="metric",
            source="prometheus",
            service="catalog-service",
            timestamp=now() - timedelta(seconds=1),
            payload={"name": "memory_bytes", "value": 100},
        )
        runtime.bus.publish(event)
        deadline = time.monotonic() + 5
        while client.get("/events/background-one").status_code != 200:
            assert time.monotonic() < deadline, "Background loop never consumed Redis telemetry"
            time.sleep(0.02)
        assert client.get("/ready").status_code == 200
        snapshot = client.get("/runtime").json()
        assert snapshot["enabled"] is True and snapshot["last_tick_at"]
        assert snapshot["collector_enabled"] is False
        assert "runtime-test" not in client.get("/runtime").text
    assert runtime.last_tick is not None
    last_tick = runtime.last_tick
    time.sleep(0.05)
    assert runtime.last_tick == last_tick


def test_background_dependency_failure_is_visible_and_not_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("eventbus.eventbus.Redis.from_url", lambda *a, **k: fake)
    settings = Settings(api_token="runtime-test", worker_enabled=True, redis_url="redis://unused")
    app = create_app(settings, Repository("sqlite:///:memory:"))

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise ConnectionError("dependency lost")

    monkeypatch.setattr(app.state.runtime.delivery, "tick", fail)
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer runtime-test"
        deadline = time.monotonic() + 3
        while not client.get("/runtime").json()["error"]:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert client.get("/runtime").json()["error"] == "ConnectionError"
        assert client.get("/ready").status_code == 503
        assert client.get("/health").status_code == 200  # liveness is not readiness
