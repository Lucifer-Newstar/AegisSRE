"""Per-application OTLP instrumentation, configured before ASGI startup.

Import this module only with the telemetry[observability] extra installed.
No process-global provider or root-handler mutation is needed. Each application
owns its exporters, service-scoped log handler and shutdown lifecycle.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, LogRecordExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from prometheus_client import Counter, Histogram
from starlette.responses import Response


class TraceLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        context = trace.get_current_span().get_span_context()
        body = {"message": record.getMessage(), "level": record.levelname}
        if context.is_valid:
            body["trace_id"] = f"{context.trace_id:032x}"
            body["span_id"] = f"{context.span_id:016x}"
        return json.dumps(body, ensure_ascii=False)


@dataclass
class TelemetryHandle:
    service_logger: logging.Logger
    tracer: TracerProvider | None = None
    logs: LoggerProvider | None = None
    handler: LoggingHandler | None = None
    closed: bool = False

    def flush(self) -> None:
        if self.tracer:
            self.tracer.force_flush(timeout_millis=3000)
        if self.logs:
            self.logs.force_flush(timeout_millis=3000)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.handler:
            self.service_logger.removeHandler(self.handler)
        self.flush()
        if self.logs:
            self.logs.shutdown()
        if self.tracer:
            self.tracer.shutdown()


def configure_observability(
    application: FastAPI,
    service: str,
    environment: str,
    endpoint: str,
    requests: Counter,
    duration: Histogram,
    *,
    span_exporter: SpanExporter | None = None,
    log_exporter: LogRecordExporter | None = None,
) -> TelemetryHandle:
    if application.middleware_stack is not None:
        raise RuntimeError("Configure observability before ASGI startup")
    if getattr(application.state, "telemetry", None) is not None:
        raise RuntimeError("Observability is already configured for this application")
    handle = TelemetryHandle(logging.getLogger(service))

    @application.middleware("http")
    async def measure(request: Request, call_next: Any) -> Response:
        started, status = time.perf_counter(), 500
        try:
            response: Response = await call_next(request)
            status = response.status_code
            return response
        finally:
            # Route templates avoid a new time series per user/product/event ID.
            path = str(getattr(request.scope.get("route"), "path", "unmatched"))
            requests.labels(service, request.method, path, str(status)).inc()
            duration.labels(service, request.method, path).observe(time.perf_counter() - started)

    if endpoint or span_exporter is not None or log_exporter is not None:
        resource = Resource.create({"service.name": service, "deployment.environment": environment})
        handle.tracer = TracerProvider(resource=resource)
        if span_exporter is None and endpoint:
            span_exporter = OTLPSpanExporter(endpoint=endpoint, insecure=endpoint.startswith("http://"), timeout=3)
        if span_exporter is not None:
            handle.tracer.add_span_processor(BatchSpanProcessor(span_exporter))
        FastAPIInstrumentor.instrument_app(application, tracer_provider=handle.tracer)
        if log_exporter is None and endpoint:
            log_exporter = OTLPLogExporter(endpoint=endpoint, insecure=endpoint.startswith("http://"), timeout=3)
        if log_exporter is not None:
            handle.logs = LoggerProvider(resource=resource)
            handle.logs.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
            handle.handler = LoggingHandler(level=logging.INFO, logger_provider=handle.logs)
            handle.handler.setFormatter(TraceLogFormatter())
            # Exporter diagnostics must not recursively export themselves.
            handle.service_logger.addHandler(handle.handler)

    previous_lifespan = application.router.lifespan_context

    @asynccontextmanager
    async def managed_lifespan(app: FastAPI) -> AsyncIterator[Any]:
        try:
            async with previous_lifespan(app) as state:
                yield state
        finally:
            handle.close()

    application.router.lifespan_context = managed_lifespan
    application.state.telemetry = handle
    return handle
