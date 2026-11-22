from __future__ import annotations

import httpx
import pytest
from incidents_service.collectors import ReadClient
from incidents_service.config import Settings
from incidents_service.models import now
from incidents_service.slo import readout


@pytest.mark.parametrize(
    "case,measured",
    [
        ("complete", True),
        ("partial", False),
        ("missing", False),
        ("zero-traffic", False),
        ("stale", False),
        ("failed-scrapes", False),
        ("missing-counter", False),
    ],
)
def test_slo_budget_is_not_fabricated_from_partial_windows(case: str, measured: bool) -> None:
    def request(req: httpx.Request) -> httpx.Response:
        expression = req.url.params["query"]
        value = 2.0
        if "count_over_time" in expression:
            value = 172800.0 if case != "partial" else 100
            if "http_server" in expression and case == "missing-counter":
                value = 100
        elif "sum_over_time" in expression:
            value = 172800.0 if case != "failed-scrapes" else 172700
        elif "timestamp" in expression:
            value = 60 if case == "stale" else 0
        elif "increase" in expression:
            value = 5 if 'status=~"5.."' in expression else 100000
            if case == "zero-traffic":
                value = 0
        rows = (
            [] if case == "missing" else [{"metric": {}, "value": [now().timestamp(), str(value)]}]
        )
        return httpx.Response(
            200, json={"status": "success", "data": {"resultType": "vector", "result": rows}}
        )

    result = readout(
        Settings(dev_mode=True, prometheus_url="http://configured-prometheus"),
        "catalog-service",
        ReadClient(httpx.Client(transport=httpx.MockTransport(request))),
    )
    assert (result["budget_remaining_fraction"] is not None) is measured
    assert result["authorizes_execution"] is False
    if measured:
        assert result["budget_remaining_fraction"] == 0.95
