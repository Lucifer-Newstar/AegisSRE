"""catalog-service — the AegisShop vertical slice.

Purpose of this module
----------------------
* Expose the catalog REST API (list + get products) from in-memory seed data.
* Emit Prometheus metrics (request rate/latency) and OpenTelemetry traces
  (to the OTel collector when configured) — the A1 observability flow.
* Provide the ``FaultHook`` stub: chaos-lab readiness (A11), demo-only.

The layout mirrors the platform service template (backend/services/_template)
so conventions stay identical across the repo.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from aegisshop_faults import configure_fault_hooks
from fastapi import FastAPI, HTTPException
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    ProcessCollector,
    generate_latest,
)
from starlette.responses import Response
from telemetry.instrumentation import configure_observability

from catalog_service.catalog import CATALOG, Product
from catalog_service.config import settings
from catalog_service.logging import setup_logging

logger = setup_logging(settings.service_name, settings.environment)

# ── Prometheus metrics (conventions from the service template) ───────────────
# Own CollectorRegistry per service — several services share metric names by
# convention, so a global registry would collide in combined test runs.
METRIC_REGISTRY = CollectorRegistry()
ProcessCollector(registry=METRIC_REGISTRY)

REQUESTS = Counter(
    "http_server_requests_total",
    "Total HTTP requests",
    ["service", "method", "path", "status"],
    registry=METRIC_REGISTRY,
)
REQUEST_DURATION = Histogram(
    "http_server_request_duration_seconds",
    "HTTP request duration",
    ["service", "method", "path"],
    registry=METRIC_REGISTRY,
)
# A shop-domain metric: catalog size — handy for the Grafana dashboard.
CATALOG_SIZE = Counter("catalog_products_total", "Total products served", ["service"], registry=METRIC_REGISTRY)


# ── OpenTelemetry tracing (same graceful pattern as the template) ────────────




# ── FaultHook stub (chaos readiness — implemented in A11) ────────────────────
class FaultHook:
    """Demo-only interface for chaos-lab fault injection (A11).

    The chaoslab calls ``inject()``/``restore()`` on the running service;
    real implementations (CPU saturation, latency, 5xx) land with the chaos
    lab milestone. This stub documents the contract and keeps the slice
    honest about what is NOT implemented yet.
    """

    def inject(self, fault_type: str) -> None:
        logger.warning(f"fault injection requested but not implemented: {fault_type}")

    def restore(self) -> None:
        logger.warning("fault restore requested but not implemented")


fault_hook = FaultHook()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Startup: wire tracing; seed catalog metrics."""
    CATALOG_SIZE.labels(settings.service_name).inc(len(CATALOG))
    logger.info("catalog-service starting", extra={"products": len(CATALOG)})
    yield
    logger.info("catalog-service stopped")


app = FastAPI(title="AegisShop Catalog Service", version="0.1.0", lifespan=lifespan)


@app.get("/")
def root() -> dict[str, str]:
    """Service metadata."""
    return {"service": settings.service_name, "environment": settings.environment, "status": "ok"}


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "healthy"}


@app.get("/ready")
def ready() -> dict[str, str]:
    """Readiness probe (in-memory catalog → always ready in this slice)."""
    return {"status": "ready"}


@app.get("/metrics")
def metrics() -> Response:
    """Prometheus scrape endpoint."""
    return Response(generate_latest(METRIC_REGISTRY), media_type=CONTENT_TYPE_LATEST)


# ── Catalog API ───────────────────────────────────────────────────────────────

@app.get("/products", response_model=list[Product])
def list_products() -> list[Product]:
    """List all products in the catalog."""
    logger.info("listing products")
    return list(CATALOG.values())[:settings.catalog_max_products]


@app.get("/products/{product_id}", response_model=Product, responses={404: {"description": "unknown product"}})
def get_product(product_id: str) -> Product:
    """Fetch a single product by id; 404 when unknown."""
    product = CATALOG.get(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail=f"product {product_id} not found")
    return product


@app.get("/faults")
def list_faults() -> dict[str, list[str]]:
    """Advertise the supported fault hooks (chaos-lab contract, A11)."""
    return {"implemented": [], "planned": ["cpu-saturation", "latency", "http-5xx", "crash"]}


configure_fault_hooks(app)


configure_observability(
    app, settings.service_name, settings.environment,
    settings.otel_exporter_otlp_endpoint, REQUESTS, REQUEST_DURATION,
)
