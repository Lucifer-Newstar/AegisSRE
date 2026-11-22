"""Real PostgreSQL regression for the shared metadata store."""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from aegis_storage import DocumentStore

DATABASE_URL = os.getenv("AEGIS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AEGIS_TEST_DATABASE_URL not configured")


def test_postgres_metadata_mutations_are_serialized() -> None:
    namespace = f"storage-test-{uuid.uuid4().hex}"
    stores = [DocumentStore(namespace, DATABASE_URL) for _ in range(4)]
    stores[0].put("counter", {"count": 0})

    def increase(index: int) -> None:
        def change(body: dict[str, Any] | None) -> dict[str, Any]:
            assert body is not None
            return {"count": int(body["count"]) + 1}

        stores[index % len(stores)].mutate("counter", change)

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(increase, range(40)))
        assert stores[-1].get("counter") == {"count": 40}
        stores[0].close()
        reopened = DocumentStore(namespace, DATABASE_URL)
        assert reopened.get("counter") == {"count": 40}
        reopened.close()
    finally:
        for store in stores:
            store.close()
