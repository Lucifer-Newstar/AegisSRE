"""A4-A9 API. Production mode requires a bearer token, including for reads."""

from __future__ import annotations

import asyncio
import hmac
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from prometheus_client import CollectorRegistry, Counter, generate_latest
from pydantic import Field
from starlette.responses import Response

from incidents_service import deployment_intelligence as deploy_intel
from incidents_service.config import Settings
from incidents_service.engine import DomainError, ReliabilityLoop
from incidents_service.intelligence import AskRequest, AskResult, Intelligence, IntelligenceError
from incidents_service.knowledge import KnowledgeStore
from incidents_service.knowledge_indexer import KnowledgeIndexer
from incidents_service.kubernetes_evidence import KubernetesEvidence
from incidents_service.models import Decision, Event, StrictModel, now
from incidents_service.repository import Repository
from incidents_service.runtime import Runtime

logger = logging.getLogger(__name__)

bearer = HTTPBearer(auto_error=False)


class ModeIn(Decision):
    mode: Literal["observe", "recommend", "auto-safe"]


class KnowledgeSearch(StrictModel):
    query: str = Field(min_length=1, max_length=2000)
    service: str = Field(min_length=1, max_length=63)
    limit: int = Field(default=5, ge=1, le=10)
    kind: Literal["runbook", "incident", "service", "failure_pattern"] | None = None


class RiskPreview(StrictModel):
    service: str
    deployment_id: str = Field(
        min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )
    revision: str = Field(min_length=1, max_length=200)
    attributes: dict[str, Any]


class IngestIn(StrictModel):
    events: list[Event] = Field(min_length=1, max_length=100)


def create_app(
    settings: Settings | None = None,
    repository: Repository | None = None,
    *,
    kube_source: KubernetesEvidence | None = None,
) -> FastAPI:
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

    runtime = Runtime(loop) if config.worker_enabled else None
    knowledge = KnowledgeStore(repo) if config.knowledge_enabled else None
    indexer = KnowledgeIndexer(knowledge, config) if knowledge else None
    intelligence = Intelligence(repo, config, knowledge)
    kubernetes = (
        (kube_source or KubernetesEvidence(config)) if config.kube_evidence_enabled else None
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        loop.sweep(recover_interrupted=True)
        stop = asyncio.Event()
        if indexer:
            indexer.seed()

        async def index_knowledge() -> None:
            assert indexer is not None
            while not stop.is_set():
                try:
                    await asyncio.to_thread(indexer.refresh)
                except Exception as exc:
                    indexer.failures["index"] = type(exc).__name__
                    logger.error("Knowledge refresh failed (%s)", type(exc).__name__)
                with suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=60)

        async def work() -> None:
            assert runtime is not None
            failures = 0
            while not stop.is_set():
                try:
                    await asyncio.to_thread(runtime.tick)
                    failures = 0
                except Exception as exc:
                    failures += 1
                    runtime.last_error = type(exc).__name__
                    logger.error("Reliability worker tick failed (%s)", type(exc).__name__)
                delay = min(30, 2 ** min(failures, 5)) if failures else 1
                with suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=delay)

        async def collect_kubernetes() -> None:
            assert kubernetes is not None and runtime is not None
            while not stop.is_set():
                try:
                    for event in await kubernetes.collect():
                        await asyncio.to_thread(runtime.delivery.stage, event)
                    if kubernetes.error in {"cluster_throttled", "cluster_access_denied"}:
                        # Do not keep hitting an account after throttling/auth denial.
                        break
                except Exception as exc:
                    kubernetes.error = "cluster_staging_failed"
                    logger.error("Kubernetes evidence staging failed (%s)", type(exc).__name__)
                with suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=config.kube_poll_seconds)

        task = asyncio.create_task(work()) if runtime else None
        knowledge_task = asyncio.create_task(index_knowledge()) if indexer else None
        kubernetes_task = asyncio.create_task(collect_kubernetes()) if kubernetes else None
        try:
            yield
        finally:
            stop.set()
            if task is not None:
                # Wait for in-flight I/O before closing shared connections.
                await task
            if knowledge_task is not None:
                await knowledge_task
            if kubernetes_task is not None:
                await kubernetes_task
            if kubernetes:
                await kubernetes.close()
            if indexer:
                indexer.close()
            if runtime:
                runtime.close()
            await intelligence.close()
            if repository is None:
                repo.close()

    application = FastAPI(title="AegisSRE Reliability API", version="0.1.0", lifespan=lifespan)
    application.state.loop = loop
    application.state.runtime = runtime
    application.state.intelligence = intelligence
    application.state.kubernetes = kubernetes
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3030", "http://127.0.0.1:3030"],
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    def authorized(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)] = None,
    ) -> None:
        if config.dev_mode and not config.api_token:
            return
        supplied = credentials.credentials if credentials else ""
        if not supplied or not hmac.compare_digest(supplied.encode(), config.api_token.encode()):
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

    @application.exception_handler(IntelligenceError)
    async def intelligence_error(_: Request, exc: IntelligenceError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @application.get("/intelligence/status", dependencies=[Depends(authorized)])
    def intelligence_status() -> dict[str, object]:
        return intelligence.status()

    @application.get("/intelligence/tools", dependencies=[Depends(authorized)])
    def intelligence_tools(
        service: str, question: str = Query(default="service health", min_length=1, max_length=2000)
    ) -> dict[str, Any]:
        try:
            return intelligence.tools.collect(service, question).model_dump(mode="json")
        except ValueError as exc:
            raise HTTPException(422, "Invalid evidence scope or query") from exc

    @application.post("/ask", dependencies=[Depends(authorized)], response_model=AskResult)
    async def ask(body: AskRequest) -> AskResult:
        return await intelligence.ask(body)

    @application.post("/incidents/{incident_id}/investigate", dependencies=[Depends(authorized)])
    async def investigate(incident_id: str) -> dict[str, object]:
        return await intelligence.investigate(incident_id)

    @application.get("/incidents/{incident_id}/investigation", dependencies=[Depends(authorized)])
    def investigation(incident_id: str) -> dict[str, object]:
        return intelligence.investigation(incident_id)

    @application.get("/health")
    def health() -> dict[str, str]:
        return {
            "status": "healthy",
            "service": "incidents-service",
            "executor": config.executor,
            "analysis_engine": "deterministic-evidence-v1",
        }

    @application.get(
        "/ready",
        dependencies=[Depends(authorized)],
        responses={
            503: {
                "description": "A dependency, worker or configured evidence source is unavailable"
            }
        },
    )
    def ready() -> dict[str, str]:
        try:
            with repo.transaction() as tx:
                tx.get_state("autonomy", {})
            if runtime is not None and not runtime.ready():
                raise HTTPException(503, "Delivery worker or evidence sources not ready")
            if kubernetes is not None and (
                kubernetes.error
                or kubernetes.succeeded_at is None
                or (now() - kubernetes.succeeded_at).total_seconds()
                > max(60, config.kube_poll_seconds * 2)
            ):
                raise HTTPException(503, "Kubernetes evidence is not ready")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(503, "A required dependency is unavailable") from exc
        return {"status": "ready"}

    @application.get("/runtime", dependencies=[Depends(authorized)])
    def runtime_status() -> dict[str, Any]:
        snapshot = runtime.snapshot() if runtime else {"enabled": False, "collector_enabled": False}
        return {
            **snapshot,
            "kubernetes": kubernetes.snapshot() if kubernetes else {"enabled": False},
        }

    @application.get("/metrics", dependencies=[Depends(authorized)])
    def scrape() -> Response:
        return Response(
            generate_latest(metrics), media_type="text/plain; version=0.0.4; charset=utf-8"
        )

    @application.get("/anomaly-samples", dependencies=[Depends(authorized)])
    def anomaly_samples(service: str, metric: str) -> dict[str, Any]:
        from incidents_service.anomaly_windows import windows
        from incidents_service.metric_history import METRICS
        if service not in config.allowed_targets or metric not in METRICS:
            raise HTTPException(422, "Select an allowed service and metric")
        with repo.transaction() as tx:
            return windows(tx, service, config.environment, metric, datetime.now(UTC))
    @application.get("/deployment-intelligence/canary", dependencies=[Depends(authorized)])
    def canary_analysis(service: str) -> dict[str, Any]:
        from incidents_service.canary import analyze
        if service not in config.allowed_targets:
            raise HTTPException(422, "Select an allowed service")
        return analyze(config, service)
    @application.get("/deployment-intelligence/trends", dependencies=[Depends(authorized)])
    def deployment_trends(service: str) -> dict[str, Any]:
        from incidents_service.deployment_trends import trend

        if service not in config.allowed_targets:
            raise HTTPException(422, "Select an allowed service")
        with repo.transaction() as tx:
            return trend(tx, service, config.environment, datetime.now(UTC))

    @application.get("/deployment-intelligence/review", dependencies=[Depends(authorized)])
    def deployment_review(service: str, rollout_id: str = Query(max_length=80)) -> dict[str, Any]:
        from incidents_service.deployment_trends import report

        if service not in config.allowed_targets:
            raise HTTPException(422, "Select an allowed service")
        with repo.transaction() as tx:
            result = report(tx, rollout_id, service, config.environment)
        if result is None:
            raise HTTPException(404, "Deployment review not found")
        return result
    @application.post("/deployment-intelligence/risk-preview", dependencies=[Depends(authorized)])
    def risk_preview(body: RiskPreview) -> dict[str, Any]:
        from pydantic import ValidationError

        from incidents_service.change_risk import Attributes, preview

        if body.service not in config.allowed_targets:
            raise HTTPException(422, "Select an allowed service")
        try:
            attributes = Attributes.model_validate(body.attributes)
        except ValidationError as exc:
            raise HTTPException(422, "Invalid change attributes") from exc
        with repo.transaction() as tx:
            try:
                return preview(
                    tx,
                    body.service,
                    config.environment,
                    body.deployment_id,
                    body.revision,
                    attributes,
                )
            except ValueError as exc:
                raise HTTPException(
                    409, "Preview identity already bound to different inputs"
                ) from exc

    @application.get("/slo", dependencies=[Depends(authorized)])
    def slo_readout(service: str) -> dict[str, Any]:
        from incidents_service.slo import readout
        if service not in config.allowed_targets:
            raise HTTPException(422, "Select an allowed service")
        return readout(config, service)
    @application.get("/deployment-intelligence/risk", dependencies=[Depends(authorized)])
    def deployment_risk(
        service: str, limit: int = Query(default=50, ge=1, le=100)
    ) -> dict[str, Any]:
        from incidents_service.deployment_risk import scores

        if service not in config.allowed_targets:
            raise HTTPException(422, "Select an allowed service")
        with repo.transaction() as tx:
            return scores(tx, service, config.environment, datetime.now(UTC), limit)

    @application.get("/deployment-intelligence/rollouts", dependencies=[Depends(authorized)])
    def deployment_rollouts(
        service: str, limit: int = Query(default=100, ge=1, le=500)
    ) -> dict[str, Any]:
        if service not in config.allowed_targets:
            raise HTTPException(422, "Select an allowed service")
        with repo.transaction() as tx:
            deploy_intel.finalize(tx)
            rows = tx.list_rollouts(
                service=service, environment=config.environment, limit=limit + 1
            )
        return {
            "service": service,
            "environment": config.environment,
            "rollouts": rows[:limit],
            "truncated": len(rows) > limit,
            "authorizes_execution": False,
        }

    @application.get("/deployment-intelligence/summary", dependencies=[Depends(authorized)])
    def deployment_summary(service: str, since: datetime | None = None) -> dict[str, Any]:
        if service not in config.allowed_targets:
            raise HTTPException(422, "Select an allowed service")
        point = now()
        start = since or point - timedelta(days=30)
        if start.tzinfo is None or not point - timedelta(days=90) <= start <= point:
            raise HTTPException(422, "Select an aware start within the preceding 90 days")
        with repo.transaction() as tx:
            deploy_intel.finalize(tx)
            return deploy_intel.summary(
                tx, service=service, environment=config.environment, since=start.astimezone(UTC)
            )

    @application.get("/knowledge/status", dependencies=[Depends(authorized)])
    def knowledge_status() -> dict[str, Any]:
        return indexer.snapshot() if indexer else {"enabled": False}

    @application.post("/knowledge/search", dependencies=[Depends(authorized)])
    def knowledge_search(body: KnowledgeSearch) -> dict[str, Any]:
        if knowledge is None:
            raise HTTPException(503, "Knowledge indexing is disabled")
        if body.service not in config.allowed_targets:
            raise HTTPException(422, "Select an allowed service")
        try:
            results = knowledge.search(
                body.query,
                service=body.service,
                environment=config.environment,
                limit=body.limit,
                kind=body.kind,
            )
        except ValueError as exc:
            raise HTTPException(
                503, "Retrieval is unavailable for this corpus; inspect knowledge status"
            ) from exc
        return {
            "service": body.service,
            "environment": config.environment,
            "results": results,
            "index_status": indexer.snapshot() if indexer else {"enabled": False},
        }

    @application.get("/runbooks", dependencies=[Depends(authorized)])
    def runbooks() -> list[dict[str, Any]]:
        if knowledge is None:
            raise HTTPException(503, "Knowledge indexing is disabled")
        records: dict[str, dict[str, Any]] = {}
        for service in config.allowed_targets:
            for document in knowledge.list_documents(
                kind="runbook", service=service, environment=config.environment
            ):
                records[document["id"]] = {
                    key: value for key, value in document.items() if key != "content"
                }
        return [records[identity] for identity in sorted(records)]

    @application.get("/runbooks/{runbook_id}", dependencies=[Depends(authorized)])
    def runbook(runbook_id: str) -> dict[str, Any]:
        if knowledge is None:
            raise HTTPException(503, "Knowledge indexing is disabled")
        identity = runbook_id if runbook_id.startswith("runbook:") else "runbook:" + runbook_id
        for service in config.allowed_targets:
            document = knowledge.get_document(
                identity, service=service, environment=config.environment
            )
            if document and document["kind"] == "runbook":
                return document
        raise HTTPException(404, "Unknown runbook")

    @application.get("/incidents/{incident_id}/context", dependencies=[Depends(authorized)])
    def incident_context(incident_id: str) -> dict[str, Any]:
        if knowledge is None:
            raise HTTPException(503, "Knowledge indexing is disabled")
        with repo.transaction() as tx:
            incident = tx.incident(incident_id)
        if incident is None:
            raise HTTPException(404, "Unknown incident")
        if (
            incident.service not in config.allowed_targets
            or incident.environment != config.environment
        ):
            raise HTTPException(422, "Incident is outside the configured evidence scope")
        # Retrieval happens after the snapshot transaction closes. In particular,
        # never take a second PostgreSQL advisory lock while the first is held.
        query = (
            incident.analysis.summary + " " + " ".join(signal.metric for signal in incident.signals)
        )[:2000]
        return {
            "incident_id": incident.id,
            "evidence_ids": incident.evidence_ids,
            "knowledge": knowledge.search(
                query, service=incident.service, environment=incident.environment
            ),
            "read_only": True,
            "index_status": indexer.snapshot() if indexer else {"enabled": False},
            "authorizes_actions": False,
        }

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

    @application.get("/metric-history", dependencies=[Depends(authorized)])
    def metric_history(
        service: str = Query(min_length=1, max_length=63),
        metric: str = Query(min_length=1, max_length=100),
        hours: int = Query(default=24, ge=1, le=24),
        buckets: int = Query(default=288, ge=12, le=600),
    ) -> dict[str, Any]:
        from incidents_service.metric_history import METRICS, history

        if service not in config.allowed_targets or metric not in METRICS:
            raise HTTPException(422, "Service or metric outside configured scope")
        with repo.transaction() as tx:
            return history(tx, service, config.environment, metric, now(), hours, buckets)

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

    @application.post("/incidents/{incident_id}/notes", dependencies=[Depends(authorized)])
    def annotate(incident_id: str, body: Decision) -> dict[str, Any]:
        return loop.annotate(incident_id, body).model_dump(mode="json")

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
