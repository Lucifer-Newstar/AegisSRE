from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import httpx
import pytest
from incidents_service.collectors import Collector, ReadClient
from incidents_service.config import Settings
from incidents_service.models import now
from pydantic import ValidationError


def configured() -> Settings:
    return Settings(
        dev_mode=True,
        allowed_targets=["catalog-service"],
        prometheus_url="http://prometheus:9090",
        registry_url="http://registry:8101",
        deployments_url="http://deployments:8701",
    )


def test_fixed_collectors_preserve_timestamps_and_positive_health() -> None:
    point = now().replace(microsecond=0)
    config = configured()
    observed: list[httpx.Request] = []
    collector: Collector
    values = {
        "request_rate": 5,
        "error_rate": 0,
        "latency_p95": 0.1,
        "cpu_usage_percent": 2,
        "memory_bytes": 1024,
        "up": 1,
    }

    def respond(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        if request.url.path == "/services":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "catalog-service",
                        "status": "healthy",
                        "url": "http://169.254.169.254",
                        "last_heartbeat_at": point.isoformat(),
                        "availability_slo": 0.999,
                        "latency_slo_seconds": 1,
                    }
                ],
            )
        if request.url.path == "/deployments":
            return httpx.Response(
                200,
                json=[
                    {
                        "envelope": {
                            "id": "deploy-original",
                            "timestamp": (point - timedelta(seconds=10)).isoformat(),
                            "source": "deployment",
                            "type": "deployment",
                            "service": "catalog-service",
                            "payload": {
                                "action": "deploy",
                                "revision": "abc123",
                                "status": "succeeded",
                            },
                        }
                    }
                ],
            )
        name = next(
            name
            for name, (query, _) in collector.queries().items()
            if query == request.url.params["query"]
        )
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [
                        {
                            "metric": {"service": "catalog-service", "environment": "dev"},
                            "value": [point.timestamp(), str(values[name])],
                        }
                    ],
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        collector = Collector(config, ReadClient(client))
        events = collector.collect(point)
        assert len(events) == 8
        assert not collector.failures
        assert events[0].id == "deploy-original"
        metrics = [event for event in events if event.type == "metric"]
        assert all(event.timestamp == point for event in metrics)
        health = events[-1].payload
        assert health["status"] == "healthy"
        assert health["slo_ok"] and health["errors_ok"] and health["latency_ok"]
        assert "availability_30d" not in json.dumps(health)
        assert {request.url.host for request in observed} == {
            "prometheus",
            "registry",
            "deployments",
        }
        assert [event.id for event in collector.collect(point)] == [event.id for event in events]


@pytest.mark.parametrize(
    "problem",
    [
        "zero_traffic",
        "nan",
        "stale",
        "wrong_environment",
        "stale_health",
        "missing_latency",
        "no_slo",
        "future",
        "outage",
    ],
)
def test_missing_stale_or_idle_evidence_never_proves_recovery(problem: str) -> None:
    point = now().replace(microsecond=0)
    collector: Collector

    def respond(request: httpx.Request) -> httpx.Response:
        if problem == "outage":
            return httpx.Response(503)
        if request.url.path == "/services":
            record: dict[str, Any] = {
                "id": "catalog-service",
                "status": "healthy",
                "last_heartbeat_at": (
                    point - timedelta(seconds=90 if problem == "stale_health" else 0)
                ).isoformat(),
                "availability_slo": 0.999,
                "latency_slo_seconds": 1,
            }
            if problem == "no_slo":
                record.pop("availability_slo")
            return httpx.Response(200, json=[record])
        if request.url.path == "/deployments":
            return httpx.Response(200, json=[])
        name = next(
            name
            for name, (query, _) in collector.queries().items()
            if query == request.url.params["query"]
        )
        value: Any = 0 if name == "error_rate" else 1
        if problem == "zero_traffic" and name == "request_rate":
            value = 0
        if problem == "nan":
            value = "NaN"
        timestamp = point.timestamp() - (
            100 if problem == "stale" else -5 if problem == "future" else 0
        )
        result = [
            {
                "metric": {
                    "service": "catalog-service",
                    "environment": "prod" if problem == "wrong_environment" else "dev",
                },
                "value": [timestamp, str(value)],
            }
        ]
        if problem == "missing_latency" and name == "latency_p95":
            result = []
        return httpx.Response(
            200, json={"status": "success", "data": {"resultType": "vector", "result": result}}
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        collector = Collector(configured(), ReadClient(client))
        health = collector.collect(point)[-1].payload
        assert health["slo_ok"] is False
        if problem in {"outage", "wrong_environment"}:
            assert collector.failures


@pytest.mark.parametrize("mode", ["redirect", "oversized"])
def test_read_client_does_not_follow_redirect_or_accept_large_evidence(mode: str) -> None:
    response = (
        httpx.Response(302, headers={"Location": "http://other/secret"})
        if mode == "redirect"
        else httpx.Response(200, content=b"x" * 1_000_001)
    )
    observed: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return response

    with (
        httpx.Client(transport=httpx.MockTransport(respond)) as client,
        pytest.raises((httpx.HTTPError, ValueError)),
    ):
        ReadClient(client).get("http://configured", "/fixed")
    assert len(observed) == 1


@pytest.mark.parametrize(
    "override",
    [
        {"environment": 'dev"} OR up'},
        {"allowed_targets": ["catalog.*"]},
        {"registry_url": "http://user:secret@registry"},
        {"registry_url": "file:///etc/passwd"},
        {"worker_enabled": True},
        {"collector_enabled": True},
    ],
)
def test_collector_configuration_rejects_unsafe_or_incomplete_scope(
    override: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        Settings(dev_mode=True, **override)
