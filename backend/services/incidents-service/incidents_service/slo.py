"""Fixed request-success objective readout with explicit window coverage gates."""

from __future__ import annotations

import math
from typing import Any

import httpx

from incidents_service.collectors import ReadClient
from incidents_service.config import Settings
from incidents_service.models import now


def readout(settings: Settings, service: str, reader: ReadClient | None = None) -> dict[str, Any]:
    if service not in settings.allowed_targets:
        raise ValueError("Select an allowed service")
    result: dict[str, Any] = {
        "service": service,
        "environment": settings.environment,
        "objective": "request-success-99.9-v1",
        "target": 0.999,
        "at": now().isoformat(),
        "budget_window_days": 30,
        "budget_remaining_fraction": None,
        "status": "unavailable",
        "measurements": {},
        "authorizes_execution": False,
        "caveat": "Request-based demo objective, not time-based uptime. Missing/zero traffic is unknown. Budget is withheld without complete successful scrape coverage and a positive request denominator. No retention guarantee.",
    }
    if not settings.prometheus_url:
        return {**result, "reason": "Prometheus not configured"}
    scope = f'service="{service}",environment="{settings.environment}"'
    requests = f"http_server_requests_total{{{scope}}}"
    expressions = {
        "burn_5m": f"aegisshop:slo_burn_rate:5m{{{scope}}}",
        "burn_1h": f"aegisshop:slo_burn_rate:1h{{{scope}}}",
        "requests_30d": f"sum(increase({requests}[30d]))",
        "errors_30d": f'sum(increase(http_server_requests_total{{{scope},status=~"5.."}}[30d])) or (0 * sum(increase({requests}[30d])))',
        "successful_scrapes_30d": f"min(sum_over_time(up{{{scope}}}[30d]))",
        "request_counter_samples_30d": f"min(count_over_time({requests}[30d]))",
        "scrape_samples_30d": f"min(count_over_time(up{{{scope}}}[30d]))",
        "freshness_seconds": f"time() - min(timestamp(up{{{scope}}}))",
    }
    client = reader or ReadClient()
    try:
        evidence: dict[str, Any] = {}
        values: dict[str, float | None] = {}
        for key, expression in expressions.items():
            response = client.get(settings.prometheus_url, "/api/v1/query", {"query": expression})
            data = response["data"]
            if (
                response.get("status") != "success"
                or response.get("warnings")
                or response.get("infos")
                or data.get("resultType") != "vector"
                or len(data["result"]) > 1
            ):
                raise ValueError("Incomplete or ambiguous SLO query")
            rows = data["result"]
            value = None
            if rows:
                timestamp, raw = rows[0]["value"]
                parsed = float(raw)
                if (
                    math.isfinite(parsed)
                    and parsed >= 0
                    and 0 <= now().timestamp() - float(timestamp) <= 45
                ):
                    value = parsed
            values[key] = value
            evidence[key] = {"expression": expression, "result": rows}
        result["measurements"], result["evidence"] = values, evidence
        expected = 30 * 86400 / 15
        samples = values["scrape_samples_30d"]
        successes = values["successful_scrapes_30d"]
        covered = (
            samples is not None
            and successes is not None
            and samples >= expected
            and successes >= expected
            and values["request_counter_samples_30d"] is not None
            and values["request_counter_samples_30d"] >= expected
        )
        fresh = values["freshness_seconds"] is not None and values["freshness_seconds"] <= 45
        result["expected_scrapes_at_15s"] = expected
        result["successful_scrape_coverage"] = (
            min(1, successes / expected) if successes is not None else None
        )
        total, errors = values["requests_30d"], values["errors_30d"]
        if (
            covered
            and fresh
            and total is not None
            and total > 0
            and errors is not None
            and errors <= total
        ):
            result["budget_remaining_fraction"] = 1 - errors / (total * 0.001)
            result["status"] = "observed_complete"
        else:
            result["status"] = "partial_or_missing_window"
        return result
    except (httpx.HTTPError, KeyError, ValueError, TypeError, ArithmeticError) as exc:
        return {**result, "reason": type(exc).__name__}
    finally:
        if reader is None:
            client.close()
