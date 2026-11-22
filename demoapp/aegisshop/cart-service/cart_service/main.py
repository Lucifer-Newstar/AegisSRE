"""cart-service — per-user shopping carts with isolated Redis persistence."""

from __future__ import annotations

from typing import Any

from aegisshop_faults import configure_fault_hooks
from fastapi import HTTPException
from pydantic import BaseModel, Field
from redis.exceptions import RedisError

from cart_service.config import settings
from cart_service.runtime import build_app, health_routes, instrument_middleware
from cart_service.store import CartStore

PRICES: dict[str, float] = {'p-001': 39.99, 'p-002': 89.99, 'p-003': 329.0, 'p-004': 49.5, 'p-005': 24.99}

app = build_app("AegisShop Cart Service")
health_routes(app)

store = CartStore(settings.shop_redis_url)


class AddItem(BaseModel):
    product_id: str
    quantity: int = Field(..., ge=1, le=10000)


def _cart(user_id: str, quantities: dict[str, int] | None = None) -> dict[str, Any]:
    if quantities is None:
        quantities = store.quantities(user_id)
    items: list[dict[str, Any]] = [{"product_id": product_id, "quantity": quantity, "unit_price": PRICES[product_id]}
             for product_id, quantity in sorted(quantities.items())]
    return {"user_id": user_id, "items": items,
            "total": round(sum(item["unit_price"] * item["quantity"] for item in items), 2)}


def reset_carts() -> None:
    store.reset_local()


@app.get("/ready", responses={503: {"description": "cart Redis unavailable"}})
def ready() -> dict[str, str]:
    try:
        store.ping()
    except RedisError:
        raise HTTPException(status_code=503, detail="cart Redis unavailable") from None
    return {"status": "ready"}


@app.get("/cart/{user_id}", responses={503: {"description": "cart Redis unavailable"}})
def get_cart(user_id: str) -> dict[str, Any]:
    try:
        return _cart(user_id)
    except (RedisError, ValueError, KeyError):
        raise HTTPException(status_code=503, detail="cart Redis unavailable") from None


@app.post("/cart/{user_id}/items", responses={404: {"description": "unknown product"}, 503: {"description": "cart Redis unavailable"}})
def add_item(user_id: str, body: AddItem) -> dict[str, Any]:
    if body.product_id not in PRICES:
        raise HTTPException(status_code=404, detail=f"product {body.product_id} not found")
    try:
        return _cart(user_id, store.add(user_id, body.product_id, body.quantity))
    except (RedisError, ValueError, KeyError):
        raise HTTPException(status_code=503, detail="cart Redis unavailable") from None


configure_fault_hooks(app)
instrument_middleware(app)
