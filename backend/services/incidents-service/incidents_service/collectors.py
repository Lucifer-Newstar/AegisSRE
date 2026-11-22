"""Fixed, read-only collectors. Missing, stale and zero-traffic data fail closed.

Registry URLs are metadata only, never fetch destinations. All network origins
come from operator configuration; redirects and oversized responses are denied.
The health SLO check is a fresh one-minute recovery-window SLI, not a fabricated
30-day availability or error-budget measurement.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from telemetry import EventEnvelope

from incidents_service.config import Settings
from incidents_service.models import now


class ReadClient:
    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=3, follow_redirects=False)
        self.owned = client is None

    def get(self, base: str, path: str, params: dict[str, str] | None = None) -> Any:
        started = time.monotonic()
        chunks: list[bytes] = []
        size = 0
        with self.client.stream(
            "GET", base.rstrip("/") + path, params=params, timeout=3, follow_redirects=False
        ) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > 1_000_000 or time.monotonic() - started > 5:
                    raise ValueError("Evidence response exceeds size/time bound")
                chunks.append(chunk)
        return json.loads(b"".join(chunks))

    def close(self) -> None:
        if self.owned:
            self.client.close()


def _event(
    kind: str, source: str, service: str, environment: str, at: datetime, payload: dict[str, Any],
    *, trace_id: str | None = None,
) -> EventEnvelope:
    content = {
        "type": kind,
        "source": source,
        "service": service,
        "environment": environment,
        "timestamp": at.isoformat(),
        "payload": payload,
    }
    if trace_id is not None:
        content["trace_id"] = trace_id
    event_id = "collect_" + hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
    return EventEnvelope(
        id=event_id,
        type=kind,
        source=source,
        service=service,
        environment=environment,
        timestamp=at,
        trace_id=trace_id,
        payload=payload,
    )


class Collector:
    def __init__(self, settings: Settings, reader: ReadClient | None = None):
        self.config = settings
        self.reader = reader or ReadClient()
        self.failures: dict[str, str] = {}
        self.evidence_cursor = 0

    def queries(self) -> dict[str, tuple[str, str]]:
        scope = f'environment="{self.config.environment}",service=~"{"|".join(self.config.allowed_targets)}"'
        labels = "service,environment"
        requests = f'http_server_requests_total{{{scope},path!~"/(metrics|health|ready)"}}'
        rate = f"sum by ({labels}) (rate({requests}[1m]))"
        errors = (
            f'http_server_requests_total{{{scope},status=~"5..",path!~"/(metrics|health|ready)"}}'
        )
        ratio = (
            f"((sum by ({labels}) (rate({errors}[1m]))) or on ({labels}) (0 * ({rate}))) / ({rate})"
        )
        histogram = f'http_server_request_duration_seconds_bucket{{{scope},path!~"/(metrics|health|ready)"}}'
        fresh = f"(time() - max by ({labels}) (timestamp({requests}))) <= 45"

        def process(metric: str, expression: str) -> str:
            return f"({expression}) and on ({labels}) ((time() - max by ({labels}) (timestamp({metric}{{{scope}}}))) <= 45)"

        return {
            "request_rate": (f"({rate}) and on ({labels}) ({fresh})", "requests/second"),
            "error_rate": (f"({ratio}) and on ({labels}) ({fresh})", "ratio"),
            "latency_p95": (
                f"histogram_quantile(0.95, sum by ({labels},le) (rate({histogram}[1m]))) and on ({labels}) ({fresh})",
                "seconds",
            ),
            "cpu_usage_percent": (
                process(
                    "process_cpu_seconds_total",
                    f"max by ({labels}) (rate(process_cpu_seconds_total{{{scope}}}[1m])) * 100",
                ),
                "percent_of_one_core",
            ),
            "memory_bytes": (
                process(
                    "process_resident_memory_bytes",
                    f"max by ({labels}) (process_resident_memory_bytes{{{scope}}})",
                ),
                "bytes",
            ),
            "up": (process("up", f"min by ({labels}) (up{{{scope}}})"), "boolean"),
        }

    def _metric(self, name: str, query: str, unit: str, at: datetime) -> list[EventEnvelope]:
        body = self.reader.get(
            self.config.prometheus_url,
            "/api/v1/query",
            {"query": query, "time": str(at.timestamp())},
        )
        if (
            not isinstance(body, dict)
            or body.get("status") != "success"
            or body["data"]["resultType"] != "vector"
        ):
            raise ValueError("Expected a successful Prometheus instant vector")
        rows = body["data"]["result"]
        if not isinstance(rows, list) or len(rows) > len(self.config.allowed_targets):
            raise ValueError("Unexpected Prometheus series cardinality")
        result: list[EventEnvelope] = []
        seen: set[str] = set()
        for row in rows:
            service = row["metric"].get("service")
            environment = row["metric"].get("environment")
            timestamp, value = float(row["value"][0]), float(row["value"][1])
            if service not in self.config.allowed_targets or environment != self.config.environment:
                raise ValueError("Prometheus returned an out-of-scope series")
            if service in seen:
                raise ValueError("Prometheus returned duplicate aggregate series")
            seen.add(service)
            if not math.isfinite(timestamp) or not math.isfinite(value):
                continue
            if not 0 <= at.timestamp() - timestamp <= 45 or value < 0:
                continue
            if name in {"error_rate", "up"} and value > 1:
                continue
            result.append(
                _event(
                    "metric",
                    "prometheus",
                    service,
                    environment,
                    datetime.fromtimestamp(timestamp, UTC),
                    {"name": name, "labels": {}, "value": value, "unit": unit},
                )
            )
        return result

    def collect(self, at: datetime | None = None) -> list[EventEnvelope]:
        point = (at or now()).astimezone(UTC).replace(microsecond=0)
        self.failures = {}
        collected: list[EventEnvelope] = []
        metadata: dict[str, dict[str, Any]] = {}
        if self.config.registry_url:
            try:
                services = self.reader.get(self.config.registry_url, "/services")
                if not isinstance(services, list) or len(services) > 1000:
                    raise ValueError("Invalid registry catalogue")
                metadata = {
                    str(item["id"]): item
                    for item in services
                    if item["id"] in self.config.allowed_targets
                }
            except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
                self.failures["registry"] = type(exc).__name__
        if self.config.deployments_url:
            try:
                deployments = self.reader.get(
                    self.config.deployments_url, "/deployments", {"limit": "500"}
                )
                if not isinstance(deployments, list) or len(deployments) > 500:
                    raise ValueError("Invalid deployment history")
                for item in deployments:
                    event = EventEnvelope.model_validate(item["envelope"])
                    if event.type != "deployment":
                        raise ValueError("Non-deployment in deployment history")
                    if (
                        event.service in self.config.allowed_targets
                        and event.environment == self.config.environment
                    ):
                        collected.append(event)
            except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
                self.failures["deployments"] = type(exc).__name__
        if self.config.prometheus_url:
            for name, (query, unit) in self.queries().items():
                try:
                    collected.extend(self._metric(name, query, unit, point))
                except (httpx.HTTPError, ValueError, TypeError, KeyError, OverflowError) as exc:
                    self.failures[f"prometheus:{name}"] = type(exc).__name__
        health_at = at.astimezone(UTC) if at is not None else now()
        values: dict[str, dict[str, float]] = {}
        for event in collected:
            if event.type == "metric" and 0 <= (health_at - event.timestamp).total_seconds() <= 45:
                values.setdefault(event.service, {})[str(event.payload["name"])] = float(
                    event.payload["value"]
                )
        for service in self.config.allowed_targets:
            record, signals = metadata.get(service, {}), values.get(service, {})
            fresh = False
            try:
                heartbeat = datetime.fromisoformat(
                    str(record["last_heartbeat_at"]).replace("Z", "+00:00")
                )
                fresh = (
                    heartbeat.tzinfo is not None
                    and 0 <= (health_at - heartbeat).total_seconds() <= 45
                )
                availability, latency = (
                    float(record["availability_slo"]),
                    float(record["latency_slo_seconds"]),
                )
                if not (0 < availability < 1 and math.isfinite(latency) and latency > 0):
                    raise ValueError("Invalid service SLO")
            except (KeyError, TypeError, ValueError):
                availability, latency, fresh = 1.0, 0.0, False
            traffic = signals.get("request_rate", 0) > 0
            errors_ok = (
                traffic and "error_rate" in signals and signals["error_rate"] <= 1 - availability
            )
            latency_ok = traffic and "latency_p95" in signals and signals["latency_p95"] <= latency
            healthy = fresh and record.get("status") == "healthy" and signals.get("up") == 1
            collected.append(
                _event(
                    "health",
                    "registry",
                    service,
                    self.config.environment,
                    health_at,
                    {
                        "service": service,
                        "status": "healthy" if healthy else "unknown",
                        "checks": {"readiness": "ok" if healthy else "unknown"},
                        "errors_ok": bool(fresh and errors_ok),
                        "latency_ok": bool(fresh and latency_ok),
                        "slo_ok": bool(healthy and errors_ok and latency_ok),
                        "measurement_window_seconds": 60,
                        "traffic_observed": traffic,
                    },
                )
            )
        # Stagger one service per tick so slow evidence stores do not multiply
        # the fast delivery loop's network work by the entire service catalogue.
        from incidents_service.signal_evidence import SignalEvidence

        service = self.config.allowed_targets[self.evidence_cursor % len(self.config.allowed_targets)]
        self.evidence_cursor += 1
        evidence = SignalEvidence(self.config, self.reader)
        logs: list[EventEnvelope] = []
        try:
            logs = evidence.logs(service, point)
            collected.extend(logs)
        except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
            self.failures[f"loki:{service}"] = type(exc).__name__
        try:
            identity = next((event.trace_id for event in logs if event.trace_id), None)
            collected.extend(evidence.trace(service, identity, point) if identity else evidence.traces(service, point))
        except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
            self.failures[f"tempo:{service}"] = type(exc).__name__
        return collected

    def close(self) -> None:
        self.reader.close()
