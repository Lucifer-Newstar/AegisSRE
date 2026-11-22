"""Order persistence and dependency failure are observable, not empty carts."""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import Mock
from urllib.error import URLError

import pytest
from fastapi.testclient import TestClient
from order_service.store import OrderStore
from sqlalchemy.exc import OperationalError

main = importlib.import_module("order_service.main")


def test_order_survives_store_recreation(tmp_path: Path) -> None:
    url = "sqlite:///" + str(tmp_path / "orders.db")
    first = OrderStore(url)
    first.put({"id": "ord-persistent", "user_id": "fixture", "items": [], "total": 0})
    first.close()
    second = OrderStore(url)
    assert second.get("ord-persistent") == {
        "id": "ord-persistent", "user_id": "fixture", "items": [], "total": 0
    }
    assert second.get("missing") is None
    second.close()


def test_order_lookup_binds_untrusted_id(tmp_path: Path) -> None:
    store = OrderStore("sqlite:///" + str(tmp_path / "orders.db"))
    store.put({"id": "safe", "items": []})
    assert store.get("' OR 1=1 --") is None
    assert store.get("safe") == {"id": "safe", "items": []}
    store.close()


def test_database_outage_fails_readiness_and_domain_requests_not_liveness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken = Mock()
    error = OperationalError("fixture", {}, RuntimeError("private-connection-value"))
    broken.ping.side_effect = broken.put.side_effect = broken.get.side_effect = error
    monkeypatch.setattr(main, "store", broken)
    monkeypatch.setattr(main.settings, "cart_service_url", "")
    client = TestClient(main.app)
    assert client.get("/health").status_code == 200
    responses = [client.get("/ready"), client.get("/orders/fixture"),
                 client.post("/orders", json={"user_id": "user-01"})]
    assert all(response.status_code == 503 for response in responses)
    assert all("private-connection-value" not in response.text for response in responses)


def test_cart_network_outage_is_not_an_empty_cart(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main.settings, "cart_service_url", "http://cart-service:9002")
    monkeypatch.setattr("urllib.request.urlopen", Mock(side_effect=URLError("fixture")))
    response = TestClient(main.app).post("/orders", json={"user_id": "user-01"})
    assert response.status_code == 503
    assert response.json()["detail"] == "cart dependency unavailable"


def test_postgres_unavailable_does_not_break_store_construction() -> None:
    # No server at this closed loopback endpoint. This is a real failed connect,
    # not proof of successful PostgreSQL persistence (the kind gate owns that).
    store = OrderStore("postgresql+psycopg://fixture:fixture@127.0.0.1:1/fixture")
    with pytest.raises(OperationalError):
        store.ping()
    store.close()
