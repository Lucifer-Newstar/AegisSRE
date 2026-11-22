#!/usr/bin/env python3
"""Actual HTTP shop persistence and readiness proof helpers for owned kind CI."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


def request(port: int, path: str, body: Any = None) -> tuple[int, Any]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def seed() -> dict[str, Any]:
    status, cart = request(9002, "/cart/ci-persistent-order/items", {"product_id": "p-001", "quantity": 2})
    assert status == 200 and cart["total"] == 79.98
    status, order = request(9003, "/orders", {"user_id": "ci-persistent-order"})
    assert status == 201 and order["total"] == 79.98 and order["items"] == cart["items"]
    return dict(order)


def retained(order: dict[str, Any]) -> bool:
    status, found = request(9003, "/orders/" + order["id"])
    return bool(status == 200 and found == order)


def unavailable() -> bool:
    return bool(
        request(9003, "/health")[0] == 200
        and request(9003, "/ready")[0] == 503
        and request(9003, "/orders/missing")[0] == 503
        and request(9003, "/orders", {"user_id": "ci-persistent-order"})[0] == 503
    )
