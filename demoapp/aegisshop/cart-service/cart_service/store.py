"""Redis-backed shopping carts, separate from the platform event transport."""

from __future__ import annotations

import hashlib
import threading
from typing import Any

from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry


class CartStore:
    """Atomic per-product increments. Empty URL is a developer-only local store."""

    def __init__(self, url: str = ""):
        self.client: Redis | None = (
            Redis.from_url(
                url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2,
                retry=Retry(NoBackoff(), 0),
            )
            if url else None
        )
        self._local: dict[str, dict[str, int]] = {}
        self._lock = threading.RLock()

    @staticmethod
    def key(user_id: str) -> str:
        # Fixed prefix and bounded safe key: user data cannot select another
        # Redis namespace, command, database or provider URL.
        return "aegisshop:cart:v1:" + hashlib.sha256(user_id.encode()).hexdigest()

    def ping(self) -> None:
        if self.client is not None:
            self.client.ping()

    def quantities(self, user_id: str) -> dict[str, int]:
        if self.client is not None:
            values: Any = self.client.hgetall(self.key(user_id))
            if not isinstance(values, dict):
                raise ValueError("Invalid cart response")
            return {str(key): int(value) for key, value in values.items()}
        with self._lock:
            return dict(self._local.get(user_id, {}))

    def add(self, user_id: str, product_id: str, quantity: int) -> dict[str, int]:
        if self.client is not None:
            self.client.hincrby(self.key(user_id), product_id, quantity)
            return self.quantities(user_id)
        with self._lock:
            products = self._local.setdefault(user_id, {})
            products[product_id] = products.get(product_id, 0) + quantity
            return dict(products)

    def reset_local(self) -> None:
        """Tests only. Never flush a configured Redis database, even by mistake."""
        if self.client is not None:
            raise RuntimeError("Refusing to clear persistent carts")
        with self._lock:
            self._local.clear()

    def close(self) -> None:
        if self.client is not None:
            self.client.close()
