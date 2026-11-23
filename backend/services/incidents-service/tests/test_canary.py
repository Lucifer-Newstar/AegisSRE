from __future__ import annotations

import json

import httpx
import pytest
from incidents_service.canary import analyze
from incidents_service.collectors import ReadClient
from incidents_service.config import Settings
from incidents_service.models import now


@pytest.mark.parametrize(
    "case,expected",
    [
        ("regression", "regressed"),
        ("healthy", "no_regression_observed"),
        ("missing", "insufficient"),
        ("sparse", "insufficient"),
        ("stale", "unavailable"),
        ("nan", "unavailable"),
        ("duplicate", "unavailable"),
        ("warnings", "unavailable"),
    ],
)
def test_fixed_comparison_never_turns_missing_data_into_healthy(case: str, expected: str) -> None:
    def request(req: httpx.Request) -> httpx.Response:
        query = req.url.params["query"]
        assert req.url.host == "operator-prometheus" and req.url.path == "/api/v1/query"
        assert not req.headers.get("authorization")
        values: list[float]
        if "timestamp" in query:
            values = [0, 0]
        elif "histogram_quantile" in query:
            values = [0.05, 0.06]
        elif 'status=~"5.."' in query:
            values = [0, 150 if case == "regression" else 0]
        else:
            values = [200, 20 if case == "sparse" else 200]
        rows = [
            {
                "metric": {"track": track},
                "value": [
                    now().timestamp() - (60 if case == "stale" else 0),
                    "NaN" if case == "nan" else str(value),
                ],
            }
            for track, value in zip(("stable", "canary"), values, strict=True)
        ]
        if case == "missing":
            rows = rows[:1]
        if case == "duplicate":
            rows[1]["metric"] = {"track": "stable"}
        return httpx.Response(
            200,
            json={
                "status": "success",
                "warnings": ["partial"] if case == "warnings" else [],
                "data": {"resultType": "vector", "result": rows},
            },
        )

    client = ReadClient(httpx.Client(transport=httpx.MockTransport(request)))
    result = analyze(
        Settings(dev_mode=True, prometheus_url="http://operator-prometheus"),
        "catalog-service",
        client,
    )
    assert result["status"] == expected
    assert result["authorizes_execution"] is False
    json.dumps(result, allow_nan=False)


def test_configuration_and_target_are_not_query_input() -> None:
    assert analyze(Settings(dev_mode=True), "catalog-service")["status"] == "insufficient"
    with pytest.raises(ValueError):
        analyze(Settings(dev_mode=True), 'catalog-service"} or vector(1)')
