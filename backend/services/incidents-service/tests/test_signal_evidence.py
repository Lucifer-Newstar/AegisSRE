from __future__ import annotations

import base64
import json
from datetime import timedelta
from typing import Any

import httpx
import pytest
from incidents_service.collectors import Collector, ReadClient
from incidents_service.config import Settings
from incidents_service.models import Event, now
from incidents_service.signal_evidence import SignalEvidence, trace_id

IDENTITY = "12345678901234567890123456789012"


def configured() -> Settings:
    return Settings(
        dev_mode=True,
        allowed_targets=["catalog-service"],
        loki_url="http://loki:3100",
        tempo_url="http://tempo:3200",
    )


def fixture(point: Any, *, environment: str = "dev", identity: str = IDENTITY) -> dict[str, Any]:
    ns = int((point - timedelta(seconds=1)).timestamp()) * 10**9
    return {
        "batches": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "catalog-service"}},
                        {"key": "deployment.environment", "value": {"stringValue": environment}},
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": identity,
                                "spanId": "1234567890123456",
                                "name": "GET /products",
                                "startTimeUnixNano": str(ns),
                                "endTimeUnixNano": str(ns + 1000),
                                "attributes": [
                                    {
                                        "key": "http.response.status_code",
                                        "value": {"intValue": "200"},
                                    },
                                    {
                                        "key": "authorization",
                                        "value": {"stringValue": "must-not-be-retained"},
                                    },
                                ],
                            }
                        ]
                    }
                ],
            }
        ]
    }


def test_actual_protocol_shapes_join_and_stable_ids() -> None:
    point = now().replace(microsecond=0)
    observed: list[httpx.Request] = []
    ns = int((point - timedelta(seconds=1)).timestamp()) * 10**9

    def respond(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        if request.url.host == "loki":
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {
                        "resultType": "streams",
                        "result": [
                            {
                                "stream": {
                                    "service_name": "catalog-service",
                                    "deployment_environment": "dev",
                                },
                                "values": [
                                    [
                                        str(ns),
                                        json.dumps(
                                            {
                                                "message": "request served",
                                                "level": "INFO",
                                                "trace_id": IDENTITY,
                                            }
                                        ),
                                    ]
                                ],
                            }
                        ],
                    },
                },
            )
        if request.url.path == "/api/search":
            return httpx.Response(200, json={"traces": [{"traceID": IDENTITY}]})
        return httpx.Response(
            200, json=fixture(point, identity=base64.b64encode(bytes.fromhex(IDENTITY)).decode())
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        evidence = SignalEvidence(configured(), ReadClient(client))
        logs, traces = (
            evidence.logs("catalog-service", point),
            evidence.traces("catalog-service", point),
        )
        assert logs[0].trace_id == traces[0].trace_id == IDENTITY
        assert logs[0].id == evidence.logs("catalog-service", point)[0].id
        assert "authorization" not in traces[0].payload["attributes"]
        for event in [*logs, *traces]:
            Event.model_validate(event.model_dump())
        assert all(
            'deployment.environment="dev"' in request.url.params["q"]
            for request in observed
            if request.url.path == "/api/search"
        )
        assert all(request.url.host in {"loki", "tempo"} for request in observed)


@pytest.mark.parametrize("value", ["../metadata", "http://evil.invalid/", "0" * 32, "abc"])
def test_trace_id_rejects_path_injection_and_invalid_ids(value: str) -> None:
    with pytest.raises(ValueError):
        trace_id(value)


def test_cross_environment_batches_are_never_disclosed() -> None:
    point = now().replace(microsecond=0)
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=fixture(point, environment="prod"))
        )
    ) as client:
        evidence = SignalEvidence(configured(), ReadClient(client))
        assert evidence.trace("catalog-service", IDENTITY, point) == []
        with pytest.raises(ValueError, match="allowed service"):
            evidence.trace("arbitrary-service", IDENTITY, point)


def test_unrelated_trace_and_oversized_search_are_rejected() -> None:
    point = now().replace(microsecond=0)
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=fixture(point, identity="f" * 32))
        )
    ) as client:
        evidence = SignalEvidence(configured(), ReadClient(client))
        with pytest.raises(ValueError, match="unrelated trace"):
            evidence.trace("catalog-service", IDENTITY, point)
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"traces": [{"traceID": IDENTITY}] * 2})
        )
    ) as client, pytest.raises(ValueError, match="Excessive"):
        SignalEvidence(configured(), ReadClient(client)).traces("catalog-service", point)


def test_loki_scope_is_verified_even_if_backend_ignores_selector() -> None:
    point = now()

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "resultType": "streams",
                    "result": [
                        {
                            "stream": {
                                "service_name": "catalog-service",
                                "deployment_environment": "prod",
                            },
                            "values": [],
                        }
                    ],
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client, pytest.raises(ValueError, match="out-of-scope"):
        SignalEvidence(configured(), ReadClient(client)).logs("catalog-service", point)


def test_collection_staggers_targets_and_reports_backend_failures() -> None:
    services: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.host == "loki":
            services.append(request.url.params["query"])
            return httpx.Response(503)
        return httpx.Response(200, json={"traces": []})

    config = configured()
    config.allowed_targets = ["catalog-service", "cart-service"]
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        collector = Collector(config, ReadClient(client))
        collector.collect()
        assert "loki:catalog-service" in collector.failures
        collector.collect()
        assert "loki:cart-service" in collector.failures
        assert "loki:catalog-service" in collector.failures
    assert len(services) == 2
    assert 'service_name="catalog-service"' in services[0]
    assert 'service_name="cart-service"' in services[1]


def test_tempo_search_zero_trimmed_hex_normalizes_without_weakening_otlp_ids() -> None:
    point = now().replace(microsecond=0)
    expected = "00" + IDENTITY[2:]
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/search":
            return httpx.Response(200, json={"traces":[{"traceID":expected.lstrip("0")}]})
        return httpx.Response(200,json=fixture(point, identity=expected))

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        evidence=SignalEvidence(configured(),ReadClient(client))
        result=evidence.traces("catalog-service",point)
        assert result and result[0].trace_id==expected
        assert requests[-1].url.path=="/api/traces/"+expected
    with pytest.raises(ValueError):
        trace_id("abc")
