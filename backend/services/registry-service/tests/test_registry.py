"""Tests for registry-service (A2)."""

import pytest
from fastapi.testclient import TestClient
from registry_service.main import app
from registry_service.store import store

client = TestClient(app)


def setup_function() -> None:
    store.reset()


def test_health() -> None:
    assert client.get("/health").json() == {"status": "healthy"}


def test_ready() -> None:
    resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


def test_list_includes_seed() -> None:
    rows = client.get("/services").json()
    ids = {row["id"] for row in rows}
    assert "catalog-service" in ids
    assert "registry-service" in ids


def test_register_and_get() -> None:
    resp = client.post(
        "/services",
        json={"id": "ml-service", "name": "ML", "url": "http://ml-service:8501"},
    )
    assert resp.status_code == 201
    got = client.get("/services/ml-service")
    assert got.status_code == 200
    assert got.json()["name"] == "ML"


def test_unknown_service_404() -> None:
    assert client.get("/services/no-such").status_code == 404


def test_heartbeat_unknown_404() -> None:
    assert client.post("/services/no-such/heartbeat").status_code == 404


def test_heartbeat_updates() -> None:
    before = client.get("/services/catalog-service").json()["last_heartbeat_at"]
    resp = client.post("/services/catalog-service/heartbeat")
    assert resp.status_code == 200
    after = resp.json()["last_heartbeat_at"]
    assert after is not None
    assert before is None or after >= before


def test_probe_reader_only_for_exact_builtin_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock

    from registry_service.config import settings
    from registry_service.store import ServiceRecord

    monkeypatch.setattr(settings, "read_token", "local-test-reader")
    response = MagicMock()
    response.__enter__.return_value.status = 200
    opener = MagicMock()
    opener.open.return_value = response
    monkeypatch.setattr("urllib.request.build_opener", lambda *args: opener)
    for identity, url, allowed in [
        ("registry-service", "http://registry-service:8101", True),
        ("deployments-service", "http://deployments-service:8701", True),
        ("catalog-service", "http://catalog-service:9001", False),
        ("registry-service", "http://registry-service:9001", False),
        ("registry-service", "http://registry-service:8101/other", False),
        ("other-service", "http://registry-service:8101", False),
    ]:
        record = ServiceRecord(id=identity, name=identity, url=url)
        record.probe_ready()
        request = opener.open.call_args.args[0]
        assert request.get_header("Authorization") == ("Bearer local-test-reader" if allowed else None)
        assert record.status == "healthy"
