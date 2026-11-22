from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from registry_service.main import app
from registry_service.store import RegistryStore, ServiceRecord, store


@pytest.fixture(autouse=True)
def isolated_registry() -> None:
    store.reset()


def test_update_delete_and_disallow_metadata_probe_urls() -> None:
    client = TestClient(app)
    body = {
        "id": "catalog-service",
        "name": "Catalogue",
        "url": "http://catalog-service:9001",
        "owner": "operator",
        "availability_slo": 0.995,
        "latency_slo_seconds": 0.5,
    }
    assert client.put("/services/catalog-service", json=body).status_code == 200
    got = client.get("/services/catalog-service").json()
    assert got["owner"] == "operator" and got["availability_slo"] == 0.995
    assert (
        client.post("/services", json={**body, "url": "http://169.254.169.254"}).status_code == 422
    )
    assert (
        client.post(
            "/services", json={**body, "url": "http://user:password@catalog-service:9001"}
        ).status_code
        == 422
    )
    assert client.delete("/services/catalog-service").status_code == 204
    assert client.get("/services/catalog-service").status_code == 404
    assert client.delete("/services/catalog-service").status_code == 404


def test_registry_is_durable_and_deleted_seeds_stay_deleted(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path}/registry.db"
    first = RegistryStore(url)
    assert first.get("catalog-service") is not None
    first.register("catalog-service", "changed", "http://catalog-service:9001", owner="operator")
    assert first.delete("cart-service")
    first.documents.close()
    reopened = RegistryStore(url)
    record = reopened.get("catalog-service")
    assert record and record.name == "changed" and record.owner == "operator"
    assert reopened.get("cart-service") is None
    assert reopened.heartbeat("cart-service") is None
    reopened.documents.close()


def test_readiness_reports_real_storage_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable() -> None:
        raise ConnectionError("storage unavailable")

    monkeypatch.setattr(store.documents, "ping", unavailable)
    response = TestClient(app).get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "dependencies": {"storage": "unreachable"}}


def test_probe_cannot_follow_redirects() -> None:
    requests: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            self.send_response(302)
            self.send_header("Location", "/must-not-be-probed")
            self.end_headers()

        def log_message(self, fmt: str, *args: Any) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        record = ServiceRecord(id="test", name="test", url=f"http://127.0.0.1:{server.server_port}")
        record.probe_ready()
        assert record.status == "unhealthy" and record.last_heartbeat_at is None
        assert requests == ["/ready"]
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_probe_completion_cannot_resurrect_deletion_or_overwrite_metadata() -> None:
    snapshot = store.get("catalog-service")
    assert snapshot is not None
    store.register("catalog-service", "new name", "http://catalog-service:9001", owner="new owner")
    snapshot.status = "healthy"
    store._save_probe(snapshot)
    current = store.get("catalog-service")
    assert current and current.owner == "new owner"
    store.delete("catalog-service")
    store._save_probe(snapshot)
    assert store.get("catalog-service") is None
