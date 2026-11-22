"""FastAPI app factory for AegisSRE services (reference template).

Endpoints every service must expose (used by Compose/K8s probes and the
prometheus scrape job):
  * ``GET /health``   — liveness (no dependencies checked)
  * ``GET /ready``    — readiness (dependency checks go here per service)
  * ``GET /metrics``  — Prometheus-format metrics (prometheus-client)
  * ``GET /``         — service metadata (name, version, env)

Tracing: when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set, OpenTelemetry exports
traces to the OTel collector (gRPC); otherwise a no-op provider keeps the
service fully functional offline. Copy this module as the starting point
for every new platform service.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.responses import Response
from telemetry.instrumentation import configure_observability

from template_service.config import settings
from template_service.logging import setup_logging

# ── Logging ───────────────────────────────────────────────────────────────────
logger = setup_logging(settings.service_name, settings.environment)

# ── Prometheus metrics ────────────────────────────────────────────────────────
# Names follow the platform metric conventions (see telemetry-model.md).
# Each service uses its OWN CollectorRegistry: several AegisSRE services
# share identical metric names by convention, so a shared/global registry
# would collide when modules are imported in one process (e.g. CI test runs).
METRIC_REGISTRY = CollectorRegistry()

REQUESTS = Counter(
    "http_server_requests_total",
    "Total HTTP requests received",
    ["service", "method", "path", "status"],
    registry=METRIC_REGISTRY,
)
REQUEST_DURATION = Histogram(
    "http_server_request_duration_seconds",
    "HTTP request duration in seconds",
    ["service", "method", "path"],
    registry=METRIC_REGISTRY,
)

# ── OpenTelemetry (tracing) ───────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Application startup/shutdown hooks, wrapped by per-app telemetry ownership."""
    logger.info("service starting", extra={"port": settings.service_port})
    yield
    logger.info("service stopped")


app = FastAPI(title=f"AegisSRE {settings.service_name}", version="0.1.0", lifespan=lifespan)


@app.get("/")
def root() -> dict[str, str]:
    """Service metadata — handy for debugging and integration tests."""
    return {"service": settings.service_name, "environment": settings.environment, "status": "ok"}


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe: the process is up. No dependencies checked."""
    return {"status": "healthy"}


@app.get("/ready")
def ready() -> dict[str, str]:
    """Readiness probe: dependencies reachable.

    Services extend this with real dependency checks (e.g. Postgres ping);
    the template checks nothing besides process liveness.
    """
    return {"status": "ready"}


@app.get("/metrics")
def metrics() -> Response:
    """Prometheus scrape endpoint (content-type: text/plain; version=0.0.4)."""
    return Response(generate_latest(METRIC_REGISTRY), media_type=CONTENT_TYPE_LATEST)


configure_observability(app, settings.service_name, settings.environment, settings.otel_exporter_otlp_endpoint, REQUESTS, REQUEST_DURATION)
