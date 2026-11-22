"""Read-only, evidence-linked cause ranking. This is not an LLM.

No prose in a log, trace or model response is allowed to choose an executable
command. Plans are created by trusted code and independently checked by policy.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from incidents_service.models import Analysis, Event, Plan, Signal

PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "database_outage",
        ("connection refused", "database unavailable", "postgres", "database timeout"),
    ),
    ("memory_exhaustion", ("oomkilled", "out of memory", "memory limit")),
    ("container_crash", ("crashloopbackoff", "back-off restarting", "container exited")),
    ("config_error", ("invalid configuration", "missing configuration", "config error")),
    ("dependency_failure", ("upstream unavailable", "dependency unavailable", "upstream timeout")),
    ("network_latency", ("network delay", "connection timed out", "packet loss")),
    ("http_5xx", ("http 500", "internal server error", "http 503")),
)


def analyze(
    event: Event, signals: list[Signal], evidence: list[dict[str, Any]]
) -> tuple[Analysis, Plan, str | None]:
    supporting: list[str] = [s.event_id for s in signals]
    candidates: list[dict[str, Any]] = []
    deployment: dict[str, Any] | None = None
    for item in evidence:
        timestamp = datetime.fromisoformat(str(item["timestamp"]).replace("Z", "+00:00"))
        age = (event.timestamp - timestamp).total_seconds()
        if not 0 <= age <= 1800:
            continue
        payload = item["payload"]
        if (
            item["type"] == "deployment"
            and payload.get("action") == "deploy"
            and deployment is None
        ):
            deployment = item
        if item["type"] in {"log", "k8s_event", "trace"}:
            message = str(payload).lower()
            for cause, words in PATTERNS:
                if any(word in message for word in words):
                    candidates.append(
                        {
                            "cause": cause,
                            "confidence": 0.7,
                            "evidence_ids": [item["id"], *supporting],
                        }
                    )
                    supporting.append(item["id"])
                    break
    correlated_id: str | None = None
    if deployment:
        correlated_id = str(deployment["id"])
        supporting.append(correlated_id)
        candidates.append(
            {
                "cause": "faulty_deployment",
                "confidence": 0.65,
                "evidence_ids": [correlated_id, *[s.event_id for s in signals]],
            }
        )
    if not candidates:
        name = " ".join(s.metric for s in signals).lower()
        cause = (
            "cpu_saturation"
            if "cpu" in name
            else "memory_exhaustion"
            if "memory" in name
            else "traffic_spike"
            if "request_rate" in name
            else "unknown"
        )
        candidates.append({"cause": cause, "confidence": 0.5, "evidence_ids": supporting.copy()})
    candidates.sort(key=lambda h: float(h["confidence"]), reverse=True)
    best = candidates[0]
    summary = f"Probable {best['cause'].replace('_', ' ')} affecting {event.service}. "
    summary += "; ".join(
        f"{s.metric}: {s.observed:g} vs baseline {s.baseline_mean:g}" for s in signals
    )
    analysis = Analysis(
        summary=summary,
        confidence="medium" if best["confidence"] >= 0.65 else "low",
        evidence_ids=list(dict.fromkeys(supporting)),
        hypotheses=candidates,
    )
    plan = Plan(
        action="escalate",
        target=event.service,
        reason="No known safe remediation for this evidence",
        risk="high",
        impact="No workload changes. An operator must investigate.",
    )
    if (
        best["cause"] == "faulty_deployment"
        and deployment
        and deployment["payload"].get("previous_revision")
    ):
        plan = Plan(
            action="rollback",
            target=event.service,
            reason="Recent deployment precedes anomalous metrics",
            revision=str(deployment["payload"]["previous_revision"]),
            risk="high",
            reversible=True,
            impact="Restore the previous deployment revision. Requests may be interrupted during rollout.",
        )
    elif best["cause"] in {"cpu_saturation", "traffic_spike"}:
        plan = Plan(
            action="scale",
            target=event.service,
            reason="Capacity hypothesis from observed load; live replica policy preflight required",
            risk="low",
            reversible=True,
            impact="Add one replica only after live managed-deployment checks. No scale-down.",
        )
    elif best["cause"] in {"container_crash", "memory_exhaustion"}:
        plan = Plan(
            action="restart",
            target=event.service,
            reason=str(best["cause"]),
            risk="medium",
            impact="Rolling restart of the selected workload; may interrupt requests. No data deletion.",
        )
    return analysis, plan, correlated_id
