from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from incidents_service.config import Settings
from incidents_service.engine import DomainError, ReliabilityLoop
from incidents_service.main import create_app
from incidents_service.policy import Policy, Rule
from incidents_service.repository import Repository
from test_autonomous_worker import configured


def test_update_requires_observe_cas_new_version_and_survives_restart() -> None:
    repo = Repository("sqlite:///:memory:")
    settings = Settings(dev_mode=True)
    loop = ReliabilityLoop(repo, settings)
    changed = Policy(version="2", rules={"scale": Rule(risk="forbidden")})
    with pytest.raises(DomainError, match="observe"):
        loop.update_policy(changed, "1", "operator")
    loop.set_mode("observe", "operator")
    with pytest.raises(DomainError, match="changed"):
        loop.update_policy(changed, "old", "operator")
    assert loop.update_policy(changed, "1", "operator") == changed
    reopened = ReliabilityLoop(repo, settings)
    with repo.transaction() as tx:
        assert reopened.current_policy(tx) == changed
        assert tx.get_state("autonomy", {})["mode"] == "observe"
        assert tx.audits(None, 20)[0]["action"] == "policy.updated"
    with pytest.raises(DomainError, match="immutable"):
        reopened.update_policy(Policy(version="1"), "2", "operator")


def test_new_policy_blocks_existing_plan_across_worker_instances(monkeypatch: pytest.MonkeyPatch) -> None:
    loop, key = configured()
    peer = ReliabilityLoop(loop.repo, loop.settings)
    loop.set_mode("observe", "operator")
    loop.update_policy(Policy(version="2", rules={"scale": Rule(risk="forbidden")}), "1", "operator")
    loop.set_mode("auto-safe", "operator")
    monkeypatch.setattr(peer.executor, "policy_context", lambda _: {"current_replicas": 2})
    monkeypatch.setattr(peer.executor, "run", lambda *a, **k: pytest.fail("Forbidden action ran"))
    assert peer.run_automatic() == 0
    with loop.repo.transaction() as tx:
        item = tx.incident(key)
        assert item and item.status == "investigating"


def test_reserved_action_prevents_policy_change() -> None:
    loop, key = configured()
    loop.set_mode("observe", "operator")
    with loop.repo.transaction() as tx:
        item = tx.incident(key)
        assert item
        item.status = "remediating"
        tx.save_incident(item)
    with pytest.raises(DomainError, match="reserved"):
        loop.update_policy(Policy(version="2"), "1", "operator")


def test_authenticated_policy_api_validates_and_persists() -> None:
    with TestClient(create_app(Settings(api_token="unit"), Repository("sqlite:///:memory:"))) as http:
        body: dict[str, Any] = {"actor": "operator", "expected_version": "1", "policy": Policy(version="2").model_dump(mode="json")}
        assert http.post("/policy", json=body).status_code == 401
        http.headers["Authorization"] = "Bearer unit"
        assert http.post("/policy", json=body).status_code == 409
        http.post("/autonomy", json={"actor": "operator", "mode": "observe"})
        assert http.post("/policy", json=body).status_code == 200
        assert http.get("/policy").json()["version"] == "2"
        assert http.get("/autonomy").json()["policy"]["version"] == "2"
        assert http.post("/policy", json=body).status_code == 409
        body["policy"]["version"] = "bad/version"
        assert http.post("/policy", json=body).status_code == 422
