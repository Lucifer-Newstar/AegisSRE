"""registry-service — A2 service catalogue and live health (P2)."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, HttpUrl

from registry_service.runtime import (
    build_app,
    health_routes,
    instrument_middleware,
    logger,
)
from registry_service.store import store

app = build_app("AegisSRE Registry Service")
health_routes(app)


class RegisterRequest(BaseModel):
    """Body for POST /services."""

    id: str = Field(min_length=1, max_length=63, pattern=r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
    name: str = Field(min_length=1, max_length=160)
    url: HttpUrl
    version: str = Field(default="0.1.0", max_length=100)
    owner: str = Field(default="unassigned", max_length=160)
    availability_slo: float = Field(default=0.999, gt=0, lt=1)
    latency_slo_seconds: float = Field(default=1.0, gt=0, le=3600)


class Ready(BaseModel):
    status: str = Field(default="ready")
    dependencies: dict[str, str]


@app.get(
    "/ready", response_model=Ready, responses={503: {"description": "a dependency is unreachable"}}
)
def ready() -> Ready | JSONResponse:
    try:
        store.documents.ping()
    except Exception:
        return JSONResponse(
            {"status": "not_ready", "dependencies": {"storage": "unreachable"}}, status_code=503
        )
    return Ready(dependencies={store.documents.engine.dialect.name: "ok"})


@app.get("/services")
def list_services(
    status: str | None = Query(default=None),
    include_heartbeats: bool = Query(default=True),
) -> list[dict[str, Any]]:
    if status is not None and status not in {"healthy", "degraded", "unhealthy", "unknown"}:
        raise HTTPException(status_code=422, detail="invalid status filter")
    return store.list(status=status, include_heartbeats=include_heartbeats)


@app.post("/services", status_code=201, responses={422: {"description": "invalid payload"}})
def register_service(body: RegisterRequest) -> dict[str, Any]:
    try:
        rec = store.register(
            body.id,
            body.name,
            str(body.url),
            body.version,
            owner=body.owner,
            availability_slo=body.availability_slo,
            latency_slo_seconds=body.latency_slo_seconds,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    logger.info("registered service", extra={"id": rec.id})
    return rec.as_dict(skip_refresh=True)


@app.get("/services/{service_id}", responses={404: {"description": "unknown service"}})
def get_service(service_id: str) -> dict[str, Any]:
    rec = store.get(service_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"service {service_id} not found")
    return rec.as_dict(skip_refresh=True)


@app.post("/services/{service_id}/heartbeat", responses={404: {"description": "unknown service"}})
def heartbeat(service_id: str) -> dict[str, Any]:
    rec = store.heartbeat(service_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"service {service_id} not found")
    return rec.as_dict(skip_refresh=True)


@app.put("/services/{service_id}", responses={404: {"description": "unknown service"}})
def update_service(service_id: str, body: RegisterRequest) -> dict[str, Any]:
    if body.id != service_id:
        raise HTTPException(422, "Body id must match path")
    if store.get(service_id) is None:
        raise HTTPException(404, "Unknown service")
    return register_service(body)


@app.delete(
    "/services/{service_id}", status_code=204, responses={404: {"description": "unknown service"}}
)
def delete_service(service_id: str) -> Response:
    if not store.delete(service_id):
        raise HTTPException(404, "Unknown service")
    return Response(status_code=204)


instrument_middleware(app)
