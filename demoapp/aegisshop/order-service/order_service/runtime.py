from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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

from order_service.config import settings
from order_service.logging import setup_logging

logger = setup_logging(settings.service_name, settings.environment)

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

DEV_CORS_ORIGINS = (
    "http://localhost:3000",
    "http://localhost:3030",
)








@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info("service starting", extra={"port": settings.service_port})
    yield
    logger.info("service stopped")


def build_app(title: str) -> FastAPI:
    application = FastAPI(title=title, version="0.1.0", lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(DEV_CORS_ORIGINS),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return application


def instrument_middleware(application: FastAPI) -> None:
    configure_observability(
        application, settings.service_name, settings.environment,
        settings.otel_exporter_otlp_endpoint, REQUESTS, REQUEST_DURATION,
    )


def health_routes(application: FastAPI) -> None:
    @application.get("/")
    def root() -> dict[str, str]:
        return {
            "service": settings.service_name,
            "environment": settings.environment,
            "status": "ok",
        }

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "healthy"}

    @application.get("/metrics")
    def metrics() -> Response:
        return Response(generate_latest(METRIC_REGISTRY), media_type=CONTENT_TYPE_LATEST)
