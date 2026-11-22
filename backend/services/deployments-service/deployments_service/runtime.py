from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from aegis_security import ServiceAuth
from fastapi import Depends, FastAPI
from fastapi.security import HTTPBearer
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.responses import Response
from telemetry.instrumentation import configure_observability

from deployments_service.config import settings
from deployments_service.logging import setup_logging

logger = setup_logging(settings.service_name, settings.environment)

METRIC_REGISTRY = CollectorRegistry()

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


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info("service starting", extra={"port": settings.service_port})
    yield
    logger.info("service stopped")


def build_app(title: str) -> FastAPI:
    application = FastAPI(
        title=title,
        version="0.1.0",
        lifespan=lifespan,
        dependencies=[Depends(HTTPBearer(auto_error=False))],
        responses={
            401: {"description": "Service token required"},
            403: {"description": "Read-only token cannot mutate metadata"},
            413: {"description": "Request exceeds 64KB"},
        },
    )
    ServiceAuth.validate(settings.api_token, settings.dev_mode, settings.read_token)
    application.add_middleware(
        ServiceAuth,
        token=settings.api_token,
        read_token=settings.read_token,
        dev_mode=settings.dev_mode,
    )
    return application


def instrument_middleware(application: FastAPI) -> None:
    configure_observability(
        application,
        settings.service_name,
        settings.environment,
        settings.otel_exporter_otlp_endpoint,
        REQUESTS,
        REQUEST_DURATION,
    )


def health_routes(application: FastAPI) -> None:
    @application.get("/")
    def root() -> dict[str, str]:
        return {
            "service": settings.service_name,
            "environment": settings.environment,
            "status": "ok",
        }

    @application.get("/health", openapi_extra={"security": []})
    def health() -> dict[str, str]:
        return {"status": "healthy"}

    @application.get("/metrics", openapi_extra={"security": []})
    def metrics() -> Response:
        return Response(generate_latest(METRIC_REGISTRY), media_type=CONTENT_TYPE_LATEST)
