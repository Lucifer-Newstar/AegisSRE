"""Deliberately defective release, packaged only in the owned chaos image.

The normal catalog app and liveness remain. Product requests fail because this
release's route implementation is broken, not because of a runtime fault flag.
"""

from catalog_service.main import app
from fastapi import HTTPException


def broken_products() -> None:
    raise HTTPException(status_code=503, detail="service unavailable")


# Replace only the fixed domain route in this deliberately defective revision.
app.router.routes[:] = [route for route in app.router.routes
                       if getattr(route, "path", None) != "/products"]
app.add_api_route("/products", broken_products, methods=["GET"])
