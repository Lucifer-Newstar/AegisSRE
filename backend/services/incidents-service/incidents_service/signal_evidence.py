"""Bounded, fixed-origin Loki/Tempo evidence. Backend text is data, never commands."""

from __future__ import annotations

import base64
import json
import re
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from telemetry import EventEnvelope

if TYPE_CHECKING:
    from incidents_service.collectors import ReadClient
    from incidents_service.config import Settings


def trace_id(value: str) -> str:
    if re.fullmatch(r"[0-9a-fA-F]{32}", value):
        result = value.lower()
    else:
        raw = base64.b64decode(value, validate=True)
        if len(raw) != 16:
            raise ValueError("Invalid trace identifier")
        result = raw.hex()
    if result == "0" * 32:
        raise ValueError("Invalid zero trace identifier")
    return result


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Expected a telemetry object")
    return value


def attributes(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(items, list) or len(items) > 100:
        raise ValueError("Excessive trace attribute cardinality")
    result: dict[str, Any] = {}
    for item in items:
        item = _object(item)
        value = _object(item["value"])
        for kind in ("stringValue", "intValue", "doubleValue", "boolValue"):
            if kind in value:
                result[str(item["key"])] = value[kind]
    return result


class SignalEvidence:
    def __init__(self, settings: Settings, reader: ReadClient):
        self.config, self.reader = settings, reader

    def scope(self, service: str, at: datetime) -> tuple[int, int]:
        if service not in self.config.allowed_targets or at.tzinfo is None:
            raise ValueError("Evidence requires an allowed service and an aware timestamp")
        return int((at - timedelta(minutes=3)).timestamp()), int(at.timestamp())

    def logs(self, service: str, at: datetime) -> list[EventEnvelope]:
        from incidents_service.collectors import _event

        start, end = self.scope(service, at)
        if not self.config.loki_url:
            return []
        query = f'{{service_name="{service}",deployment_environment="{self.config.environment}"}}'
        body = self.reader.get(
            self.config.loki_url,
            "/loki/api/v1/query_range",
            {
                "query": query,
                "start": str(start * 10**9),
                "end": str(end * 10**9),
                "limit": "10",
                "direction": "backward",
            },
        )
        if (
            not isinstance(body, dict)
            or body.get("status") != "success"
            or body["data"]["resultType"] != "streams"
        ):
            raise ValueError("Expected successful Loki streams")
        rows = body["data"]["result"]
        if len(rows) > 10 or sum(len(row["values"]) for row in rows) > 10:
            raise ValueError("Excessive Loki result cardinality")
        result: list[EventEnvelope] = []
        for row in rows:
            labels = _object(row["stream"])
            if (
                labels.get("service_name") != service
                or labels.get("deployment_environment") != self.config.environment
            ):
                raise ValueError("Loki returned an out-of-scope stream")
            for value in row["values"]:
                ns, line = int(value[0]), str(value[1])
                if not start * 10**9 <= ns <= end * 10**9 or len(line) > 12000:
                    continue
                try:
                    parsed = json.loads(line)
                except ValueError:
                    parsed = {}
                parsed = parsed if isinstance(parsed, dict) else {}
                message = str(parsed.get("message", line)).encode("utf-8")[:3000].decode("utf-8", errors="ignore")
                level = str(parsed.get("level", "INFO")).upper()
                if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
                    level = "INFO"
                identity = None
                if parsed.get("trace_id"):
                    with suppress(ValueError):
                        identity = trace_id(str(parsed["trace_id"]))
                event = _event(
                    "log",
                    "loki",
                    service,
                    self.config.environment,
                    datetime.fromtimestamp(ns / 10**9, UTC),
                    {"message": message, "level": level, "attributes": {"source_timestamp_ns": str(ns)}},
                    trace_id=identity,
                )
                result.append(event)
        return result

    def traces(self, service: str, at: datetime) -> list[EventEnvelope]:
        start, end = self.scope(service, at)
        if not self.config.tempo_url:
            return []
        query = f'{{resource.service.name="{service}" && resource.deployment.environment="{self.config.environment}"}}'
        body = self.reader.get(
            self.config.tempo_url,
            "/api/search",
            {"q": query, "start": str(start), "end": str(end), "limit": "1"},
        )
        if not isinstance(body, dict):
            raise ValueError("Expected a Tempo search object")
        candidates = body.get("traces", [])
        if len(candidates) > 1:
            raise ValueError("Excessive Tempo search results")
        if not candidates:
            return []
        # Tempo search trims leading zeroes from hexadecimal IDs. Normalize
        # only this protocol field; OTLP/log identifiers keep strict parsing.
        candidate = str(_object(candidates[0])["traceID"])
        if not re.fullmatch(r"[0-9a-fA-F]{1,32}", candidate):
            raise ValueError("Invalid Tempo search trace identifier")
        identity = trace_id(candidate.zfill(32))
        return self.trace(service, identity, at)

    def trace(self, service: str, identity: str, at: datetime) -> list[EventEnvelope]:
        from incidents_service.collectors import _event

        start, end = self.scope(service, at)
        identity = trace_id(identity)
        if not self.config.tempo_url:
            return []
        body = self.reader.get(self.config.tempo_url, "/api/traces/" + identity)
        if not isinstance(body, dict):
            raise ValueError("Expected a Tempo trace object")
        batches = body.get("batches", body.get("resourceSpans", []))
        if not isinstance(batches, list) or len(batches) > 100:
            raise ValueError("Excessive trace resource batches")
        result: list[EventEnvelope] = []
        count = 0
        for batch in batches:
            batch = _object(batch)
            resource = attributes(_object(batch["resource"]).get("attributes", []))
            if (
                resource.get("service.name") != service
                or resource.get("deployment.environment") != self.config.environment
            ):
                continue  # A distributed trace legitimately contains other services.
            for scope in batch.get("scopeSpans", batch.get("instrumentationLibrarySpans", [])):
                for span in _object(scope).get("spans", []):
                    span = _object(span)
                    count += 1
                    if count > 1000:
                        raise ValueError("Excessive trace spans")
                    if len(result) >= 20:
                        continue
                    if trace_id(str(span["traceId"])) != identity:
                        raise ValueError("Tempo returned an unrelated trace")
                    began, finished = int(span["startTimeUnixNano"]), int(span["endTimeUnixNano"])
                    if (
                        not start * 10**9 <= began <= end * 10**9
                        or not 0 <= finished - began <= 3600 * 10**9
                    ):
                        continue
                    raw = attributes(span.get("attributes", []))
                    safe = {
                        key: str(value)[:500]
                        for key, value in raw.items()
                        if key
                        in {
                            "http.status_code",
                            "http.response.status_code",
                            "http.route",
                            "exception.type",
                            "error.type",
                            "db.system",
                        }
                    }
                    event = _event(
                        "trace",
                        "tempo",
                        service,
                        self.config.environment,
                        datetime.fromtimestamp(began / 10**9, UTC),
                        {
                            "name": str(span["name"])[:256],
                            "span_id": str(span["spanId"])[:64],
                            "duration_ms": (finished - began) / 10**6,
                            "status": str(span.get("status", {}).get("code", "STATUS_CODE_UNSET"))[
                                :30
                            ],
                            "attributes": safe,
                        },
                        trace_id=identity,
                    )
                    result.append(event)
        return result
