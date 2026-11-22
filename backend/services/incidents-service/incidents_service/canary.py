"""Read-only stable/canary comparison from fixed operator-configured Prometheus.

No input URLs, label selectors, query expressions or execution permissions.
"""

from __future__ import annotations

import math
from typing import Any

import httpx

from incidents_service.collectors import ReadClient
from incidents_service.config import Settings
from incidents_service.models import now

MIN_REQUESTS = 100
WINDOW_SECONDS = 300


def analyze(settings: Settings, service: str, reader: ReadClient | None = None) -> dict[str, Any]:
    if service not in settings.allowed_targets:
        raise ValueError("Select an allowed service")
    result: dict[str, Any] = {
        "service": service,
        "environment": settings.environment,
        "window_seconds": WINDOW_SECONDS,
        "minimum_requests_per_track": MIN_REQUESTS,
        "at": now().isoformat(),
        "status": "insufficient",
        "tracks": {},
        "authorizes_execution": False,
        "caveat": "Observed 5min request-window comparison, not causal attribution, a full-window coverage guarantee or automatic rollout permission.",
    }
    if not settings.prometheus_url:
        return {**result, "reason": "Prometheus is not configured"}
    client = reader or ReadClient()
    try:
        scope = f'service="{service}",environment="{settings.environment}",track=~"stable|canary",path="/products"'
        requests = f"http_server_requests_total{{{scope}}}"
        errors = f'http_server_requests_total{{{scope},status=~"5.."}}'
        histogram = f"http_server_request_duration_seconds_bucket{{{scope}}}"
        expressions = {
            "requests": f"sum by (track) (increase({requests}[5m]))",
            "errors": f"(sum by (track) (increase({errors}[5m]))) or on (track) (0 * sum by (track) (increase({requests}[5m])))",
            "latency_p95": f"histogram_quantile(0.95, sum by (track,le) (rate({histogram}[5m])))",
            "freshness": f"time() - max by (track) (timestamp({requests}))",
        }
        observed: dict[str, dict[str, float]] = {}
        evidence: dict[str, Any] = {}
        evaluation_time = now().timestamp()
        for name, expression in expressions.items():
            response = client.get(
                settings.prometheus_url,
                "/api/v1/query",
                {"query": expression, "time": str(evaluation_time)},
            )
            if (
                response.get("status") != "success"
                or response.get("warnings")
                or response.get("infos")
            ):
                raise ValueError("Incomplete Prometheus response")
            data = response["data"]
            if data.get("resultType") != "vector" or len(data["result"]) > 2:
                raise ValueError("Ambiguous comparison series")
            values: dict[str, float] = {}
            for item in data["result"]:
                track = item["metric"].get("track")
                timestamp, raw = item["value"]
                value = float(raw)
                if track not in {"stable", "canary"} or track in values:
                    raise ValueError("Ambiguous track identity")
                if (
                    not math.isfinite(value)
                    or value < 0
                    or not 0 <= now().timestamp() - float(timestamp) <= 45
                ):
                    raise ValueError("Stale or non-finite comparison")
                values[track] = value
            observed[name], evidence[name] = (
                values,
                {"expression": expression, "result": data["result"]},
            )
        result["evidence"] = evidence
        for track in ("stable", "canary"):
            if any(track not in observed[name] for name in expressions):
                return {**result, "reason": "Both tracks require complete observed series"}
            count, error_count = observed["requests"][track], observed["errors"][track]
            if count < MIN_REQUESTS or error_count > count or observed["freshness"][track] > 45:
                return {**result, "reason": "Insufficient request volume or stale/invalid track"}
            result["tracks"][track] = {
                "requests": count,
                "error_ratio": error_count / count,
                "latency_p95_seconds": observed["latency_p95"][track],
            }
        stable, canary = result["tracks"]["stable"], result["tracks"]["canary"]
        error_regression = canary["error_ratio"] > stable["error_ratio"] + 0.01
        latency_regression = canary["latency_p95_seconds"] > max(
            stable["latency_p95_seconds"] * 1.5, stable["latency_p95_seconds"] + 0.1
        )
        return {
            **result,
            "status": "regressed"
            if error_regression or latency_regression
            else "no_regression_observed",
            "reason": "Fixed comparison thresholds applied to sufficient fresh observed traffic",
            "error_regression": error_regression,
            "latency_regression": latency_regression,
            "thresholds": {
                "absolute_error_ratio_increase": 0.01,
                "latency_relative_increase": 1.5,
                "latency_absolute_increase_seconds": 0.1,
            },
        }
    except (httpx.HTTPError, KeyError, TypeError, ValueError, ArithmeticError) as exc:
        return {**result, "status": "unavailable", "reason": type(exc).__name__}
    finally:
        if reader is None:
            client.close()
