from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from aegis_storage import DocumentStore


def test_persistence_namespaces_and_atomic_mutation(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path}/metadata.db"
    first = DocumentStore("one", url)
    second = DocumentStore("two", url)
    first.put("key", {"count": 0})
    second.put("key", {"private": "other namespace"})

    def increment(_: int) -> None:
        def change(body: dict[str, Any] | None) -> dict[str, Any]:
            assert body is not None
            return {"count": int(body["count"]) + 1}

        first.mutate("key", change)

    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(increment, range(40)))
    first.close()
    reopened = DocumentStore("one", url)
    assert reopened.get("key") == {"count": 40}
    assert second.get("key") == {"private": "other namespace"}
    reopened.clear()
    assert reopened.get("key") is None
    assert second.get("key") is not None
    reopened.close()
    second.close()


def test_duplicate_insert_and_failed_mutation_leave_original() -> None:
    store = DocumentStore("test")
    assert store.put("key", {"value": "first"})[1]
    assert not store.put("key", {"value": "second"}, if_absent=True)[1]
    assert store.get("key") == {"value": "first"}

    def fail(body: dict[str, Any] | None) -> dict[str, Any]:
        raise RuntimeError("interrupted operation")

    with pytest.raises(RuntimeError):
        store.mutate("key", fail)
    assert store.get("key") == {"value": "first"}
    assert store.delete("key") is True
    assert store.delete("missing") is False
    store.close()
