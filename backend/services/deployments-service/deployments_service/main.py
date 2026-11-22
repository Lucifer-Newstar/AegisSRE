"""deployments-service — DI-1 deploy tracker (P2)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, Field

from deployments_service.runtime import build_app, health_routes, instrument_middleware, logger
from deployments_service.store import DeploymentRecord, store

app = build_app("AegisSRE Deployments Service")
health_routes(app)


class DeploymentPayloadIn(BaseModel):
    deployment_id: str | None = Field(
        default=None, min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )
    started_at: AwareDatetime | None = None
    action: Literal["deploy", "rollback", "scale", "restart"]
    revision: str = Field(min_length=1, max_length=200)
    previous_revision: str | None = None
    triggered_by: str = Field(min_length=1, max_length=100)
    status: Literal["in_progress", "succeeded", "failed"]
    change_attributes: dict[str, Any] | None = None
    risk_score: float | None = Field(default=None, ge=0, le=1)
    risk_factors: list[str] = Field(default_factory=list)
    canary: dict[str, Any] | None = None
    rollout: dict[str, Any] | None = None


class DeploymentEnvelopeIn(BaseModel):
    id: str = Field(min_length=1, max_length=160)
    schema_version: Literal["0.2"] = "0.2"
    source: Literal["deployment", "registry"]
    type: Literal["deployment"]
    service: str
    environment: str = "dev"
    severity: Literal["info", "warning", "critical"] = "info"
    timestamp: AwareDatetime
    correlation_id: str | None = None
    trace_id: str | None = None
    payload: DeploymentPayloadIn


@app.get("/ready", responses={503: {"description": "Postgres unreachable"}})
def ready() -> Any:
    try:
        store.documents.ping()
    except Exception:
        return JSONResponse({"status": "not_ready", "storage": "unreachable"}, status_code=503)
    return {"status": "ready", "storage": store.documents.engine.dialect.name}


@app.post(
    "/deployments",
    responses={
        200: {"description": "duplicate event id"},
        201: {"description": "stored"},
        422: {"description": "envelope failed schema validation"},
        409: {"description": "event id reused for different content"},
    },
)
def record_deployment(body: DeploymentEnvelopeIn) -> Any:
    document = body.model_dump(mode="json")
    # Preserve canonical old envelopes when optional lifecycle fields are absent.
    for field in ("deployment_id", "started_at", "change_attributes"):
        if document["payload"].get(field) is None:
            document["payload"].pop(field, None)
    rec = DeploymentRecord(
        event_id=body.id,
        service=body.service,
        revision=body.payload.revision,
        status=body.payload.status,
        envelope=document,
    )
    try:
        stored, created = store.put(rec)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    logger.info("deployment event", extra={"id": stored.event_id, "created": created})
    return JSONResponse(stored.as_dict(), status_code=201 if created else 200)


@app.get("/deployments")
def list_deployments(
    service: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[dict[str, Any]]:
    if status is not None and status not in {"in_progress", "succeeded", "failed"}:
        raise HTTPException(status_code=422, detail="invalid status filter")
    return [row.as_dict() for row in store.list(service=service, status=status, limit=limit)]


@app.get(
    "/deployments/{service}/latest", responses={404: {"description": "no deployments recorded"}}
)
def latest_deployment(service: str) -> dict[str, Any]:
    rec = store.latest(service)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"no deployments recorded for {service}")
    return rec.as_dict()


@app.get("/deployments/{event_id}", responses={404: {"description": "unknown event id"}})
def get_deployment(event_id: str) -> dict[str, Any]:
    rec = store.get(event_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"deployment {event_id} not found")
    return rec.as_dict()


instrument_middleware(app)
