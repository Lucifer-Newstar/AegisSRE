"""Native store checks are not successful Redis/AOF persistence proof."""

from __future__ import annotations

import importlib
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from cart_service.store import CartStore
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError

main = importlib.import_module("cart_service.main")


def test_local_cart_atomic_increments_and_copy_isolation() -> None:
    store = CartStore()
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: store.add("fixture", "p-001", 1), range(200)))
    assert store.quantities("fixture") == {"p-001": 200}
    copy = store.quantities("fixture")
    copy["p-001"] = -1
    assert store.quantities("fixture") == {"p-001": 200}
    assert store.quantities("other") == {}


def test_redis_store_uses_atomic_increment_and_bounded_hashed_keys() -> None:
    store = CartStore("redis://127.0.0.1:1/0")
    client = Mock()
    client.hgetall.return_value = {"p-001": "3"}
    store.client = client
    user = "untrusted:*\n" * 1000
    assert store.add(user, "p-001", 2) == {"p-001": 3}
    client.hincrby.assert_called_once_with(store.key(user), "p-001", 2)
    assert len(store.key(user)) < 100 and "*" not in store.key(user)
    with pytest.raises(RuntimeError, match="Refusing"):
        store.reset_local()
    client.flushdb.assert_not_called()
    client.flushall.assert_not_called()


def test_cart_redis_failure_is_not_an_empty_or_local_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken = Mock()
    error = ConnectionError("private-connection-value")
    broken.ping.side_effect = broken.quantities.side_effect = broken.add.side_effect = error
    monkeypatch.setattr(main, "store", broken)
    client = TestClient(main.app)
    assert client.get("/health").status_code == 200
    responses = [client.get("/ready"), client.get("/cart/fixture"),
                 client.post("/cart/fixture/items", json={"product_id": "p-001", "quantity": 1})]
    assert all(response.status_code == 503 for response in responses)
    assert all("private-connection-value" not in response.text for response in responses)


def test_actual_closed_port_redis_refuses_connection() -> None:
    store = CartStore("redis://127.0.0.1:1/0")
    with pytest.raises(ConnectionError):
        store.ping()
    with pytest.raises(ConnectionError):
        store.quantities("fixture")
    store.close()


def test_redis_command_semantics_without_claiming_actual_server_persistence() -> None:
    import fakeredis

    shared = fakeredis.FakeServer()
    first = CartStore()
    first.client = fakeredis.FakeRedis(server=shared, decode_responses=True)
    assert first.add("fixture", "p-001", 2) == {"p-001": 2}
    second = CartStore()
    second.client = fakeredis.FakeRedis(server=shared, decode_responses=True)
    assert second.quantities("fixture") == {"p-001": 2}
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: second.add("fixture", "p-001", 1), range(100)))
    assert first.quantities("fixture") == {"p-001": 102}
    assert second.quantities("other") == {}
    first.close()
    second.close()
