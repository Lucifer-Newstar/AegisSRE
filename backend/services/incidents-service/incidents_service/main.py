"""A4-A9 API. Production mode requires a bearer token, including for reads."""

from __future__ import annotations

import hmac
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CollectorRegistry, Counter, generate_latest
from pydantic import Field
from starlette.responses import Response

from incidents_service.config import Settings
from incidents_service.engine import DomainError, ReliabilityLoop
from incidents_service.models import Decision, Event, StrictModel
from incidents_service.repository import Repository


class ModeIn(Decision):
    mode: Literal["observe", "recommend", "auto-safe"]


class IngestIn(StrictModel):
    events: list[Event] = Field(min_length=1, max_length=100)


def create_app(settings: Settings | None = None, repository: Repository | None = None) -> FastAPI:
    config = settings or Settings()
    repo = repository or Repository(config.database_url)
    loop = ReliabilityLoop(repo, config)
    metrics = CollectorRegistry()
    ingested = Counter(
        "aegis_events_ingested_total", "Successfully processed telemetry events", registry=metrics
    )
    errors = Counter(
        "aegis_domain_errors_total", "Rejected reliability API operations", registry=metrics
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        loop.sweep(recover_interrupted=True)
        yield
        if repository is None:
            repo.close()

    application = FastAPI(title="AegisSRE Reliability API", version="0.1.0", lifespan=lifespan)
    application.state.loop = loop
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3030", "http://127.0.0.1:3030"],
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    def authorized(authorization: Annotated[str | None, Header()] = None) -> None:
        if config.dev_mode and not config.api_token:
            return
        supplied = authorization.removeprefix("Bearer ") if authorization else ""
        if not supplied or not hmac.compare_digest(supplied, config.api_token):
            raise HTTPException(status_code=401, detail="Valid bearer token required")

    @application.middleware("http")
    async def bound_body(request: Request, call_next: Any) -> Response:
        # Enforce the limit even for chunked requests, before JSON parsing.
        if request.method in {"POST", "PUT", "PATCH"}:
            chunks: list[bytes] = []
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 1_600_000:
                    return JSONResponse({"detail": "Request exceeds 1.6MB"}, status_code=413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
        response: Response = await call_next(request)
        return response

    @application.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        errors.inc()
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @application.get("/health")
    def health() -> dict[str, str]:
        return {
            "status": "healthy",
            "service": "incidents-service",
            "executor": config.executor,
            "analysis_engine": "deterministic-evidence-v1",
        }

    @application.get("/ready", dependencies=[Depends(authorized)])
    def ready() -> dict[str, str]:
        with repo.transaction() as tx:
            tx.get_state("autonomy", {})
        return {"status": "ready"}

    @application.get("/metrics", dependencies=[Depends(authorized)])
    def scrape() -> Response:
        return Response(
            generate_latest(metrics), media_type="text/plain; version=0.0.4; charset=utf-8"
        )

    @application.post("/events", dependencies=[Depends(authorized)])
    def ingest(body: Event) -> dict[str, Any]:
        result = loop.ingest(body)
        if not result["duplicate"]:
            ingested.inc()
        return result

    @application.get("/events", dependencies=[Depends(authorized)])
    def evidence(
        service: str | None = None,
        environment: str | None = None,
        event_type: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        with repo.transaction() as tx:
            return tx.recent_events(service, environment, event_type, limit)

    @application.get("/events/{event_id}", dependencies=[Depends(authorized)])
    def get_evidence(event_id: str) -> dict[str, Any]:
        with repo.transaction() as tx:
            item = tx.event(event_id)
            if item is None:
                raise HTTPException(404, "Unknown evidence")
            return item

    @application.get("/incidents", dependencies=[Depends(authorized)])
    def list_incidents(
        service: str | None = None, limit: int = Query(default=100, ge=1, le=500)
    ) -> list[dict[str, Any]]:
        loop.sweep()
        with repo.transaction() as tx:
            return [item.model_dump(mode="json") for item in tx.list_incidents(service, limit)]

    @application.get("/incidents/{incident_id}", dependencies=[Depends(authorized)])
    def incident(incident_id: str) -> dict[str, Any]:
        loop.sweep()
        with repo.transaction() as tx:
            return loop._get(tx, incident_id).model_dump(mode="json")

    @application.post("/incidents/{incident_id}/{decision}", dependencies=[Depends(authorized)])
    def decide(
        incident_id: str, decision: Literal["approve", "reject", "defer"], body: Decision
    ) -> dict[str, Any]:
        choices: dict[str, Literal["approved", "rejected", "deferred"]] = {
            "approve": "approved",
            "reject": "rejected",
            "defer": "deferred",
        }
        return loop.decide(incident_id, choices[decision], body).model_dump(mode="json")

    # Static route must precede /{decision} to avoid ambiguity. FastAPI matches
    # path order, so execute uses a distinct, explicit /actions prefix.
    @application.post("/actions/{incident_id}/execute", dependencies=[Depends(authorized)])
    def execute(incident_id: str, body: Decision) -> dict[str, Any]:
        return loop.execute(incident_id, body.actor).model_dump(mode="json")

    @application.get("/postmortems/{incident_id}", dependencies=[Depends(authorized)])
    def postmortem(incident_id: str) -> dict[str, Any]:
        return loop.postmortem(incident_id)

    @application.get("/postmortems", dependencies=[Depends(authorized)])
    def postmortems() -> list[dict[str, Any]]:
        with repo.transaction() as tx:
            ids = [i.id for i in tx.list_incidents(limit=500) if i.status == "closed"]
        return [loop.postmortem(key) for key in ids]

    @application.get("/audit", dependencies=[Depends(authorized)])
    def audits(
        incident_id: str | None = None, limit: int = Query(default=200, ge=1, le=1000)
    ) -> list[dict[str, Any]]:
        with repo.transaction() as tx:
            return tx.audits(incident_id, limit)

    @application.get("/autonomy", dependencies=[Depends(authorized)])
    def get_mode() -> dict[str, Any]:
        with repo.transaction() as tx:
            return {
                **tx.get_state("autonomy", {"mode": "recommend"}),
                "executor": config.executor,
                "policy": loop.policy.model_dump(mode="json"),
            }

    @application.post("/autonomy", dependencies=[Depends(authorized)])
    def set_mode(body: ModeIn) -> dict[str, str]:
        loop.set_mode(body.mode, body.actor)
        return {"mode": body.mode}

    return application
