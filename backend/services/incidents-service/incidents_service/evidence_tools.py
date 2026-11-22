"""Fixed read-only evidence tools. No URL, SQL, shell or action tool is accepted.

The snapshot is detached before retrieval or inference. Event text remains
untrusted even after best-effort secret redaction. Missing/stale is not healthy.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import Field

from incidents_service.knowledge import KnowledgeStore
from incidents_service.models import StrictModel, now
from incidents_service.repository import Repository

ToolName = Literal[
    "get_metrics",
    "get_logs",
    "get_traces",
    "get_health",
    "get_deployments",
    "get_k8s_events",
    "search_runbooks",
]
Status = Literal["available", "missing", "stale", "unavailable"]
TOOLS: tuple[tuple[ToolName, str, int], ...] = (
    ("get_metrics", "metric", 120),
    ("get_logs", "log", 300),
    ("get_traces", "trace", 300),
    ("get_health", "health", 120),
    ("get_deployments", "deployment", 1800),
    ("get_k8s_events", "k8s_event", 300),
)
SENSITIVE = re.compile(
    r"authorization|cookie|password|secret|token|api[_-]?key|credential|private[_-]?key", re.I
)
ASSIGNMENT = re.compile(
    r"\b(password|secret|token|api[_-]?key|authorization|cookie)\s*[:=]\s*[^\s,;]+", re.I
)
BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]+=*", re.I)
JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
URL = re.compile(
    r"(?:https?|postgres(?:ql)?(?:\+psycopg)?|mysql|redis|mongodb(?:\+srv)?|amqps?)://[^\s<>\"']+",
    re.I,
)


def clean_text(value: str, limit: int = 700) -> str:
    value = BEARER.sub("Bearer [REDACTED]", value)
    value = JWT.sub("[REDACTED_JWT]", value)
    value = ASSIGNMENT.sub(lambda match: match.group(1) + "=[REDACTED]", value)
    # URLs in telemetry can contain credentials, signed paths or query secrets.
    value = URL.sub("[URL_REDACTED]", value)
    return value.encode()[:limit].decode(errors="ignore")


def minimize(value: Any, depth: int = 0) -> Any:
    if depth > 2:
        return "[NESTED_DATA_OMITTED]"
    if isinstance(value, dict):
        return {
            clean_text(str(key), 80): "[REDACTED]"
            if SENSITIVE.search(str(key))
            else minimize(item, depth + 1)
            for key, item in list(value.items())[:8]
        }
    if isinstance(value, list):
        return [minimize(item, depth + 1) for item in value[:4]]
    if isinstance(value, str):
        return clean_text(value)
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return "[UNSUPPORTED_DATA_OMITTED]"


class EvidenceItem(StrictModel):
    id: str
    source_ref: str
    kind: str
    observed_at: str
    stale: bool
    content: dict[str, Any]


class ToolCall(StrictModel):
    name: ToolName
    status: Status
    checked_at: str
    evidence_ids: list[str]
    detail: str


class EvidenceSnapshot(StrictModel):
    service: str
    environment: str
    captured_at: str
    temporal_scope: Literal["current", "incident_window"] = "current"
    evidence_anchor: str | None = None
    window_start: str | None = None
    window_end: str | None = None
    evidence: list[EvidenceItem]
    tool_calls: list[ToolCall]
    read_only: Literal[True] = True
    authorizes_actions: Literal[False] = False
    redaction: str = "Selected bounded fields with best-effort secret redaction, not a guarantee of complete removal."

    def provider_payload(self, question: str) -> dict[str, Any]:
        # Do not send original event IDs, source URLs or metadata document paths.
        return {
            "question": clean_text(question, 2000),
            "service": self.service,
            "environment": self.environment,
            "captured_at": self.captured_at,
            "temporal_scope": self.temporal_scope,
            "evidence_anchor": self.evidence_anchor,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "evidence": [item.model_dump(exclude={"source_ref"}) for item in self.evidence],
            "tool_calls": [item.model_dump() for item in self.tool_calls],
            "requirements": "Rank hypotheses only. Cite supplied IDs. Freshness is relative to evidence_anchor. An incident_window is historical and cannot establish current health. Never claim a verified cause or an executed action.",
        }


class ReadOnlyTools:
    def __init__(
        self,
        repository: Repository,
        knowledge: KnowledgeStore | None,
        *,
        allowed_targets: list[str],
        environment: str,
    ):
        self.repo, self.knowledge = repository, knowledge
        self.allowed_targets, self.environment = frozenset(allowed_targets), environment

    def collect(
        self,
        service: str,
        question: str,
        *,
        at: datetime | None = None,
        incident_anchor: datetime | None = None,
        required_event_ids: tuple[str, ...] = (),
        excluded_document: str | None = None,
    ) -> EvidenceSnapshot:
        if service not in self.allowed_targets:
            raise ValueError("Select an allowed service")
        clock = at or now()
        if clock.tzinfo is None or (incident_anchor is not None and incident_anchor.tzinfo is None):
            raise ValueError("Evidence windows require timezones")
        if incident_anchor is not None and incident_anchor > clock:
            raise ValueError("Incident anchor is in the future")
        anchor = incident_anchor or clock
        captured = clock.isoformat()
        start = anchor - timedelta(minutes=30) if incident_anchor is not None else None
        end = min(clock, anchor + timedelta(minutes=3)) if incident_anchor is not None else None
        evidence: list[EvidenceItem] = []
        calls: list[ToolCall] = []
        # One short consistent DB snapshot. No search embedding or network while held.
        with self.repo.transaction() as tx:
            batches = [
                (
                    name,
                    kind,
                    ttl,
                    tx.recent_events(
                        service, self.environment, kind, 2, not_before=start, not_after=end
                    ),
                )
                for name, kind, ttl in TOOLS
            ]
            required = [tx.event(identity) for identity in required_event_ids[:12]]
        for name, kind, ttl, rows in batches:
            selected = []
            for item in required:
                if (
                    item is None
                    or item["service"] != service
                    or item["environment"] != self.environment
                    or item["type"] != kind
                ):
                    continue
                timestamp = datetime.fromisoformat(str(item["timestamp"]).replace("Z", "+00:00"))
                if (start is not None and timestamp < start) or (
                    end is not None and timestamp > end
                ):
                    continue
                selected.append(item)
            identities = {item["id"] for item in selected}
            rows = (selected + [item for item in rows if item["id"] not in identities])[:2]
            ids: list[str] = []
            current = False
            for row in rows:
                timestamp = datetime.fromisoformat(str(row["timestamp"]).replace("Z", "+00:00"))
                age = (anchor - timestamp).total_seconds()
                # Historical context can include three minutes after the anomaly,
                # but never observations later than this snapshot was captured.
                stale = not (-180 if incident_anchor is not None else 0) <= age <= ttl
                current = current or not stale
                identity = "event:" + hashlib.sha256(str(row["id"]).encode()).hexdigest()[:24]
                content = minimize(row["payload"])
                # A large valid event cannot crowd out every other signal source.
                if len(json.dumps(content, ensure_ascii=False).encode()) > 900:
                    content = {
                        "excerpt": clean_text(json.dumps(content, ensure_ascii=False), 450),
                        "truncated": True,
                    }
                evidence.append(
                    EvidenceItem(
                        id=identity,
                        source_ref=str(row["id"]),
                        kind=kind,
                        observed_at=timestamp.isoformat(),
                        stale=stale,
                        content=content,
                    )
                )
                ids.append(identity)
            calls.append(
                ToolCall(
                    name=name,
                    status="available" if current else "stale" if rows else "missing",
                    checked_at=captured,
                    evidence_ids=ids,
                    detail="Bounded persisted telemetry, not a live source probe. Freshness is relative to evidence_anchor, not proof of current health or healthy ingestion.",
                )
            )
        if self.knowledge is None:
            calls.append(
                ToolCall(
                    name="search_runbooks",
                    status="unavailable",
                    checked_at=captured,
                    evidence_ids=[],
                    detail="Knowledge indexing disabled",
                )
            )
        else:
            try:
                results = self.knowledge.search(
                    question[:2000],
                    service=service,
                    environment=self.environment,
                    limit=3,
                    historical_at=incident_anchor,
                    excluded_document=excluded_document,
                )
            except ValueError:
                calls.append(
                    ToolCall(
                        name="search_runbooks",
                        status="unavailable",
                        checked_at=captured,
                        evidence_ids=[],
                        detail="Retrieval unavailable; inspect knowledge status",
                    )
                )
            else:
                ids = []
                for row in results:
                    identity = "chunk:" + str(row["id"])
                    evidence.append(
                        EvidenceItem(
                            id=identity,
                            source_ref=str(row["document_id"]),
                            kind="knowledge",
                            observed_at=str(row["document_updated_at"]),
                            stale=False,
                            content={
                                "snippet": clean_text(str(row["content"]), 700),
                                "checksum": row["document_checksum"],
                                "kind": row["kind"],
                                "note": "Indexed reference material, not a current observation.",
                            },
                        )
                    )
                    ids.append(identity)
                calls.append(
                    ToolCall(
                        name="search_runbooks",
                        status="available" if ids else "missing",
                        checked_at=captured,
                        evidence_ids=ids,
                        detail="Scoped lexical vector retrieval; index timestamp is not source observation time.",
                    )
                )
        return EvidenceSnapshot(
            service=service,
            environment=self.environment,
            captured_at=captured,
            temporal_scope="incident_window" if incident_anchor is not None else "current",
            evidence_anchor=anchor.isoformat(),
            window_start=start.isoformat() if start else None,
            window_end=end.isoformat() if end else None,
            evidence=evidence,
            tool_calls=calls,
        )


Cause = Literal[
    "database_outage",
    "memory_exhaustion",
    "container_crash",
    "config_error",
    "dependency_failure",
    "network_latency",
    "http_5xx",
    "faulty_deployment",
    "cpu_saturation",
    "traffic_spike",
    "unknown",
]


class Hypothesis(StrictModel):
    cause: Cause
    confidence: Literal["low", "medium"]
    explanation: str = Field(min_length=1, max_length=700)
    evidence_ids: list[str] = Field(min_length=1, max_length=12)


class CitedAnswer(StrictModel):
    summary: str = Field(min_length=1, max_length=1500)
    evidence_ids: list[str] = Field(max_length=15)
    hypotheses: list[Hypothesis] = Field(max_length=5)
    limitations: list[str] = Field(min_length=1, max_length=8)

    def validate_citations(self, snapshot: EvidenceSnapshot) -> None:
        known = {item.id for item in snapshot.evidence}
        referenced = set(self.evidence_ids)
        for hypothesis in self.hypotheses:
            referenced.update(hypothesis.evidence_ids)
        if not referenced <= known:
            raise ValueError("unknown_citation")
        if snapshot.evidence and not self.evidence_ids:
            raise ValueError("uncited_answer")
        # A reference document alone cannot support an observed cause.
        observations = {
            item.id for item in snapshot.evidence if item.kind != "knowledge" and not item.stale
        }
        for hypothesis in self.hypotheses:
            if not observations.intersection(hypothesis.evidence_ids):
                raise ValueError("hypothesis_without_current_observation")


def evidence_only(snapshot: EvidenceSnapshot) -> CitedAnswer:
    observations = [item for item in snapshot.evidence if item.kind != "knowledge"]
    fresh = [item for item in observations if not item.stale]
    if snapshot.temporal_scope == "incident_window":
        summary = f"{len(fresh)} persisted observations near the incident anchor for {snapshot.service}. Historical evidence cannot establish current health."
    else:
        summary = f"{len(fresh)} recent persisted observations for {snapshot.service}. "
        summary += (
            "Review the cited measurements and tool freshness before drawing conclusions. This readout does not establish overall health."
            if fresh
            else "Current health is unknown: no fresh scoped observations were found."
        )
    answer = CitedAnswer(
        summary=summary,
        evidence_ids=[item.id for item in observations][:12]
        or [item.id for item in snapshot.evidence][:3],
        hypotheses=[],
        limitations=[
            "Evidence-only readout. No language model was invoked.",
            "Read-only tools cannot perform remediation.",
            "Missing or stale data is unknown, not healthy.",
        ],
    )
    answer.validate_citations(snapshot)
    return answer
