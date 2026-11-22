"""order-service — checkout with explicit durable order storage."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from opentelemetry.propagate import inject
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from order_service.config import settings
from order_service.runtime import build_app, health_routes, instrument_middleware, logger
from order_service.store import OrderStore

app = build_app("AegisShop Order Service")
health_routes(app)

store = OrderStore(settings.shop_database_url)
_DEMO_ITEMS = [{"product_id": "p-001", "quantity": 1, "unit_price": 39.99}]


class PlaceOrder(BaseModel):
    user_id: str
    cart_id: str | None = None


def reset_orders() -> None:
    store.clear()


def _items_for(user_id: str) -> list[dict[str, Any]]:
    if settings.cart_service_url:
        import urllib.error
        import urllib.request

        url = f"{settings.cart_service_url.rstrip('/')}/cart/{user_id}"
        try:
            headers: dict[str, str] = {}
            inject(headers)
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=3) as resp:
                import json

                payload = json.loads(resp.read().decode())
            return list(payload.get("items") or [])
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            logger.warning("cart lookup failed")
            raise HTTPException(status_code=503, detail="cart dependency unavailable") from exc
    if user_id == "user-01":
        return list(_DEMO_ITEMS)
    return []


@app.get("/ready", responses={503: {"description": "Postgres unreachable"}})
def ready() -> dict[str, str]:
    try:
        store.ping()
    except SQLAlchemyError:
        logger.warning("order database unavailable")
        raise HTTPException(status_code=503, detail="order database unavailable") from None
    return {"status": "ready"}


@app.post("/orders", status_code=201, responses={
    400: {"description": "empty cart or unknown user"},
    503: {"description": "order database or cart dependency unavailable"},
})
def place_order(body: PlaceOrder) -> dict[str, Any]:
    items = _items_for(body.user_id)
    if not items:
        raise HTTPException(status_code=400, detail="empty cart or unknown user")
    order_id = f"ord-{uuid4().hex}"
    total = round(sum(float(i["unit_price"]) * int(i["quantity"]) for i in items), 2)
    order = {
        "id": order_id,
        "user_id": body.user_id,
        "status": "created",
        "items": items,
        "total": total,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    try:
        store.put(order)
    except SQLAlchemyError:
        logger.warning("order database write failed")
        raise HTTPException(status_code=503, detail="order database unavailable") from None
    logger.info("order created")
    return order


@app.get("/orders/{order_id}", responses={
    404: {"description": "unknown order"}, 503: {"description": "order database unavailable"},
})
def get_order(order_id: str) -> dict[str, Any]:
    try:
        order = store.get(order_id)
    except SQLAlchemyError:
        logger.warning("order database read failed")
        raise HTTPException(status_code=503, detail="order database unavailable") from None
    if order is None:
        raise HTTPException(status_code=404, detail=f"order {order_id} not found")
    return order


instrument_middleware(app)
