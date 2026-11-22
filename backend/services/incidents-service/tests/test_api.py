from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from incidents_service.config import Settings
from incidents_service.main import create_app
from incidents_service.models import Event, now
from incidents_service.repository import Repository
from pydantic import ValidationError


def client(*, token: str = "test-token") -> TestClient:
    return TestClient(create_app(Settings(api_token=token), Repository("sqlite:///:memory:")))


def test_api_requires_authorization_and_limits_request_size() -> None:
    with client() as http:
        assert http.get("/health").status_code == 200
        assert http.get("/incidents").status_code == 401
        assert http.get("/incidents", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert http.get("/incidents", headers={"Authorization": "Bearer test-token"}).json() == []
        assert http.post("/events", content=b"x" * 1_600_001).status_code == 413


def test_api_event_and_audit() -> None:
    with client() as http:
        http.headers["Authorization"] = "Bearer test-token"
        event = Event(
            id="evt_one",
            type="metric",
            source="prometheus",
            service="catalog-service",
            payload={"name": "latency", "value": 0.1},
        )
        assert http.post("/events", json=event.model_dump(mode="json")).status_code == 200
        assert http.post("/events", json=event.model_dump(mode="json")).json()["duplicate"]
        assert http.get("/events/evt_one").json()["service"] == "catalog-service"
        assert http.get("/events/missing").status_code == 404
        assert http.get("/incidents/missing").status_code == 404
        assert http.post("/autonomy", json={"mode": "observe", "actor": "navin"}).status_code == 200
        assert http.get("/autonomy").json()["mode"] == "observe"
        assert http.get("/audit").json()[0]["action"] == "autonomy.mode.set"
        assert "aegis_events_ingested_total" in http.get("/metrics").text


def test_bad_payloads_rejected() -> None:
    with client() as http:
        http.headers["Authorization"] = "Bearer test-token"
        assert (
            http.post(
                "/events",
                json={
                    "id": "x",
                    "type": "metric",
                    "source": "prometheus",
                    "service": "catalog-service",
                    "payload": {"name": "latency", "value": "NaN"},
                },
            ).status_code
            == 422
        )
        assert (
            http.post("/autonomy", json={"mode": "unbounded", "actor": "navin"}).status_code == 422
        )
        assert (
            http.post(
                "/events",
                json={
                    "id": "x",
                    "type": "metric",
                    "source": "unknown",
                    "service": "catalog-service",
                    "payload": {"name": "latency", "value": 1},
                },
            ).status_code
            == 422
        )


def test_runtime_requires_deliberate_security_configuration() -> None:
    with pytest.raises(ValidationError, match="AEGIS_API_TOKEN"):
        Settings()
    with pytest.raises(ValidationError, match="Kubernetes execution"):
        Settings(dev_mode=True, executor="kubernetes")
    with pytest.raises(ValidationError, match="explicit LLM model"):
        Settings(dev_mode=True, llm_provider="ollama")


def test_aware_nonfuture_timestamp_required() -> None:
    base = {
        "id": "x",
        "type": "metric",
        "source": "prometheus",
        "service": "catalog-service",
        "payload": {"name": "latency", "value": 1},
    }
    with pytest.raises(ValidationError):
        Event.model_validate({**base, "timestamp": "2026-11-22T12:00:00"})
    with pytest.raises(ValidationError):
        Event.model_validate({**base, "timestamp": now() + timedelta(minutes=2)})


def test_openapi_exposes_bearer_security_without_secrets() -> None:
    with client() as http:
        schema = http.get("/openapi.json").json()
        assert schema["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"
        assert schema["paths"]["/events"]["post"]["security"] == [{"HTTPBearer": []}]
        assert "test-token" not in http.get("/openapi.json").text
