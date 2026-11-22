"""Explicit routes, not a generic URL/path proxy or a model-selected tool."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Route:
    path: str
    upstream: str
    methods: tuple[str, ...] = ("GET",)
    queries: tuple[str, ...] = ()
    asserted_actor: bool = False
    timeout_seconds: int = 10


ROUTES = (
    Route("/services", "registry", ("GET", "POST"), ("status", "include_heartbeats")),
    Route("/services/{service_id}", "registry", ("GET", "PUT", "DELETE")),
    Route("/services/{service_id}/heartbeat", "registry", ("POST",)),
    Route("/deployments", "deployments", ("GET", "POST"), ("service", "status", "limit")),
    Route("/deployments/{service}/latest", "deployments"),
    Route("/deployments/{event_id}", "deployments"),
    Route(
        "/events", "incidents", ("GET", "POST"), ("service", "environment", "event_type", "limit")
    ),
    Route("/events/{event_id}", "incidents"),
    Route("/metric-history", "incidents", queries=("service", "metric", "hours", "buckets")),
    Route("/incidents", "incidents", queries=("service", "limit")),
    Route("/incidents/{incident_id}", "incidents"),
    Route("/incidents/{incident_id}/context", "incidents"),
    Route("/incidents/{incident_id}/investigate", "incidents", ("POST",), timeout_seconds=135),
    Route("/incidents/{incident_id}/investigation", "incidents"),
    Route("/incidents/{incident_id}/{decision}", "incidents", ("POST",), asserted_actor=True),
    Route("/actions/{incident_id}/execute", "incidents", ("POST",), asserted_actor=True),
    Route("/postmortems", "incidents"),
    Route("/postmortems/{incident_id}", "incidents"),
    Route("/audit", "incidents", queries=("incident_id", "limit")),
    Route("/autonomy", "incidents", ("GET", "POST"), asserted_actor=True),
    Route("/runtime", "incidents"),
    Route("/ask", "incidents", ("POST",), timeout_seconds=135),
    Route("/deployment-intelligence/risk", "incidents", queries=("service", "limit")),
    Route("/deployment-intelligence/rollouts", "incidents", queries=("service", "limit")),
    Route("/deployment-intelligence/summary", "incidents", queries=("service", "since")),
    Route("/intelligence/status", "incidents"),
    Route("/intelligence/tools", "incidents", queries=("service", "question")),
    Route("/knowledge/status", "incidents"),
    Route("/knowledge/search", "incidents", ("POST",)),
    Route("/runbooks", "incidents"),
    Route("/runbooks/{runbook_id}", "incidents"),
)
