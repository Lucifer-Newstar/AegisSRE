from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from prometheus_client import CollectorRegistry, Counter, Histogram
from telemetry.instrumentation import configure_observability


def instrument(app: FastAPI, service: str = "test-service") -> tuple[Any, ...]:
    registry = CollectorRegistry()
    requests = Counter("test_http_total", "HTTP", ["service", "method", "path", "status"], registry=registry)
    duration = Histogram("test_duration", "Duration", ["service", "method", "path"], registry=registry)
    spans = InMemorySpanExporter()
    logs = InMemoryLogRecordExporter()  # type: ignore[no-untyped-call]
    logger = logging.getLogger(service)
    logger.setLevel(logging.INFO)
    handle = configure_observability(app, service, "test", "", requests, duration, span_exporter=spans, log_exporter=logs)
    return handle, spans, logs, registry


def test_per_app_spans_logs_context_and_shutdown() -> None:
    app = FastAPI()
    logger = logging.getLogger("test-service")

    @app.get("/products/{product}")
    def product(product: str) -> dict[str, str]:
        logger.info("product fetched")
        return {"id": product}

    handle, spans, logs, _ = instrument(app)
    trace_id = "12345678901234567890123456789012"
    with TestClient(app) as client:
        assert client.get("/products/a", headers={"traceparent": f"00-{trace_id}-1234567890123456-01"}).status_code == 200
        handle.flush()
        captured = spans.get_finished_spans()
        assert any(span.name == "GET /products/{product}" for span in captured)
        assert all(span.resource.attributes["service.name"] == "test-service" for span in captured)
        entry = logs.get_finished_logs()[0]
        body = json.loads(entry.log_record.body)
        assert body["trace_id"] == trace_id
        assert entry.log_record.trace_id == int(trace_id, 16)
        assert entry.resource.attributes["deployment.environment"] == "test"
        assert not handle.closed
    assert handle.closed
    assert handle.handler not in logger.handlers
    handle.close()


def test_service_handlers_and_exporters_do_not_cross_contaminate() -> None:
    apps = [FastAPI(), FastAPI()]
    handles = [instrument(app, f"isolated-{i}") for i, app in enumerate(apps)]
    for index, app in enumerate(apps):
        @app.get("/test")
        def endpoint(index: int = index) -> dict[str, bool]:
            logging.getLogger(f"isolated-{index}").info("isolated request")
            return {"ok": True}
    with TestClient(apps[0]) as first, TestClient(apps[1]) as second:
        first.get("/test")
        second.get("/test")
        for index, (handle, spans, logs, _) in enumerate(handles):
            handle.flush()
            assert spans.get_finished_spans()
            assert len(logs.get_finished_logs()) == 1
            assert all(entry.resource.attributes["service.name"] == f"isolated-{index}" for entry in logs.get_finished_logs())


def test_metrics_bound_route_cardinality_and_count_uncaught_errors() -> None:
    app = FastAPI()

    @app.get("/items/{item}")
    def item(item: str) -> dict[str, str]:
        return {"item": item}

    @app.get("/broken")
    def broken() -> None:
        raise RuntimeError("intentional regression fixture")

    handle, _, _, registry = instrument(app)
    with TestClient(app, raise_server_exceptions=False) as client:
        for identity in range(20):
            assert client.get(f"/items/{identity}").status_code == 200
            assert client.get(f"/unknown/{identity}").status_code == 404
        assert client.get("/broken").status_code == 500
        samples = [sample for metric in registry.collect() for sample in metric.samples if sample.name == "test_http_total"]
        assert {(sample.labels["path"], sample.labels["status"], sample.value) for sample in samples} == {("/items/{item}", "200", 20), ("unmatched", "404", 20), ("/broken", "500", 1)}
    assert handle.closed


def test_exporters_closed_even_on_lifespan_failure() -> None:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> Any:
        raise RuntimeError("startup failure")
        yield

    app = FastAPI(lifespan=lifespan)
    handle, _, _, _ = instrument(app)
    with pytest.raises(RuntimeError, match="startup failure"), TestClient(app):
        pass
    assert handle.closed


def test_duplicate_or_late_instrumentation_is_rejected() -> None:
    app = FastAPI()
    handle, _, _, _ = instrument(app)
    with pytest.raises(RuntimeError, match="already configured"):
        instrument(app)
    with TestClient(app), pytest.raises(RuntimeError, match="before ASGI startup"):
        instrument(app)
    assert handle.closed
