from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from pathlib import Path

import pytest
from deployments_service.main import app
from deployments_service.store import DeploymentRecord, DeploymentStore, _now, store
from fastapi.testclient import TestClient


def test_conflicting_event_id_is_rejected_without_losing_original() -> None:
    store.reset()
    client = TestClient(app)
    body = {
        "id": "unique",
        "type": "deployment",
        "source": "deployment",
        "service": "catalog-service",
        "timestamp": _now().isoformat(),
        "payload": {
            "action": "deploy",
            "revision": "rev-1",
            "triggered_by": "pipeline",
            "status": "succeeded",
        },
    }
    assert client.post("/deployments", json=body).status_code == 201
    different = deepcopy(body)
    different["payload"]["revision"] = "rev-2"  # type: ignore[index]
    assert client.post("/deployments", json=different).status_code == 409
    assert client.get("/deployments/unique").json()["revision"] == "rev-1"


def test_history_survives_restart_and_latest_uses_producer_time(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path}/deployments.db"
    first = DeploymentStore(url)
    assert first.list() == []  # no fake startup records for other services
    current = _now()
    for event_id, at in [("new", current), ("late-old", current - timedelta(hours=1))]:
        envelope = {"id": event_id, "timestamp": at.isoformat(), "payload": {"revision": event_id}}
        first.put(
            DeploymentRecord(
                event_id=event_id,
                service="catalog-service",
                revision=event_id,
                status="succeeded",
                envelope=envelope,
            )
        )
    first.documents.close()
    reopened = DeploymentStore(url)
    latest = reopened.latest("catalog-service")
    assert latest and latest.revision == "new"
    assert len(reopened.list()) == 2
    reopened.documents.close()


def test_real_readiness_failure_is_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail() -> None:
        raise ConnectionError("unreachable")

    monkeypatch.setattr(store.documents, "ping", fail)
    response = TestClient(app).get("/ready")
    assert response.status_code == 503 and response.json()["storage"] == "unreachable"
