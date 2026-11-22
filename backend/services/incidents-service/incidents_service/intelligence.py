"""Read-only Ask and revision-safe investigation sidecars.

Inference is outside database transactions and the telemetry delivery loop.
Durable request reservations survive failures/restarts; they are request caps,
not currency budgets. No inference output can modify a plan or execute an action.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from typing import Literal

from pydantic import Field

from incidents_service.config import Settings
from incidents_service.evidence_tools import (
    CitedAnswer,
    EvidenceSnapshot,
    ReadOnlyTools,
    evidence_only,
)
from incidents_service.knowledge import KnowledgeStore
from incidents_service.models import Incident, StrictModel, now
from incidents_service.providers import ProviderConfig, ProviderError, StructuredProvider
from incidents_service.repository import Repository


class IntelligenceError(RuntimeError):
    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status = status


class AskRequest(StrictModel):
    service: str = Field(min_length=1, max_length=63, pattern=r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
    question: str = Field(min_length=1, max_length=2000)


class AskResult(StrictModel):
    id: str
    engine: Literal["evidence-only-v1", "structured-llm-v1"]
    inference_status: Literal["disabled", "complete", "failed"]
    diagnostic: str | None = None
    model: str | None = None
    answer: CitedAnswer
    snapshot: EvidenceSnapshot
    caveat: str = "Model output is an unverified interpretation, not proof of cause, current health, or authority to act."


def revision(incident: Incident) -> str:
    return hashlib.sha256(incident.model_dump_json().encode()).hexdigest()


class Intelligence:
    def __init__(
        self,
        repository: Repository,
        config: Settings,
        knowledge: KnowledgeStore | None,
        provider: StructuredProvider | None = None,
    ):
        self.repo, self.config = repository, config
        self.tools = ReadOnlyTools(
            repository,
            knowledge,
            allowed_targets=config.allowed_targets,
            environment=config.environment,
        )
        self.provider = provider or StructuredProvider(
            ProviderConfig(
                provider=config.llm_provider,
                base_url=config.llm_url,
                model=config.llm_model,
                api_key=config.llm_api_key,
                allow_remote=config.llm_allow_remote,
                timeout_seconds=config.llm_timeout_seconds,
                max_output_tokens=config.llm_max_output_tokens,
            )
        )

    def status(self) -> dict[str, object]:
        with self.repo.transaction() as tx:
            counters = tx.get_state("inference:quota", {})
        return {
            "provider": self.provider.config.provider,
            "model": self.provider.config.model or None,
            "remote_opt_in": self.config.llm_allow_remote,
            "requests_per_hour": self.config.llm_requests_per_hour,
            "requests_per_day": self.config.llm_requests_per_day,
            "reservations": counters,
            "automatic_retries": 0,
            "write_tools": [],
            "currency_budget": None,
            "note": "Request/output bounds are not a spending budget. Failed attempts consume quota. No model is downloaded automatically.",
        }

    def reserve(self) -> None:
        clock = now()
        day, hour = clock.strftime("%Y-%m-%d"), clock.strftime("%Y-%m-%dT%H")
        with self.repo.transaction() as tx:
            previous = tx.get_state("inference:quota", {})
            daily = int(previous.get("daily", 0)) if previous.get("day") == day else 0
            hourly = int(previous.get("hourly", 0)) if previous.get("hour") == hour else 0
            if (
                daily >= self.config.llm_requests_per_day
                or hourly >= self.config.llm_requests_per_hour
            ):
                raise IntelligenceError(429, "inference_quota_exhausted")
            tx.put_state(
                "inference:quota",
                {"day": day, "hour": hour, "daily": daily + 1, "hourly": hourly + 1},
            )
            # Never persist the user's question or provider response in the audit.
            tx.append_audit(
                None,
                {
                    "at": clock.isoformat(),
                    "action": "inference_reserved",
                    "actor": "authenticated-operator",
                    "detail": "One bounded read-only inference attempt reserved; no automatic retry",
                },
                environment=self.config.environment,
            )

    async def ask(self, request: AskRequest) -> AskResult:
        try:
            snapshot = await asyncio.to_thread(
                self.tools.collect, request.service, request.question
            )
        except ValueError:
            raise IntelligenceError(422, "invalid_evidence_scope_or_query") from None
        identity = "ask_" + uuid.uuid4().hex
        if self.provider.config.provider == "disabled":
            return AskResult(
                id=identity,
                engine="evidence-only-v1",
                inference_status="disabled",
                answer=evidence_only(snapshot),
                snapshot=snapshot,
            )
        await asyncio.to_thread(self.reserve)
        try:
            answer = await self.provider.generate(
                CitedAnswer, snapshot.provider_payload(request.question)
            )
            answer.validate_citations(snapshot)
        except (ProviderError, ValueError) as exc:
            code = str(exc) if isinstance(exc, ProviderError) else "invalid_answer_citations"
            answer = evidence_only(snapshot)
            answer.limitations.insert(
                0, "Configured inference failed. This fallback contains no model answer."
            )
            return AskResult(
                id=identity,
                engine="evidence-only-v1",
                inference_status="failed",
                diagnostic=code,
                answer=answer,
                snapshot=snapshot,
            )
        return AskResult(
            id=identity,
            engine="structured-llm-v1",
            inference_status="complete",
            model=self.provider.config.model,
            answer=answer,
            snapshot=snapshot,
        )

    def incident_snapshot(self, identity: str) -> Incident:
        with self.repo.transaction() as tx:
            item = tx.incident(identity)
        if item is None:
            raise IntelligenceError(404, "unknown_incident")
        if (
            item.service not in self.config.allowed_targets
            or item.environment != self.config.environment
        ):
            raise IntelligenceError(422, "incident_outside_scope")
        return item

    async def investigate(self, identity: str) -> dict[str, object]:
        incident = await asyncio.to_thread(self.incident_snapshot, identity)
        expected = revision(incident)
        question = (
            "Investigate this incident using scoped evidence. "
            + incident.analysis.summary
            + " "
            + " ".join(item.metric for item in incident.signals)
        )[:2000]
        result = await self.ask(AskRequest(service=incident.service, question=question))
        document = {
            "incident_id": identity,
            "incident_revision": expected,
            "result": result.model_dump(mode="json"),
            "read_only": True,
            "authorizes_actions": False,
        }

        def save() -> None:
            with self.repo.transaction() as tx:
                current = tx.incident(identity)
                if current is None or revision(current) != expected:
                    raise IntelligenceError(409, "incident_changed_during_investigation")
                from datetime import datetime

                captured = datetime.fromisoformat(result.snapshot.captured_at)
                if (now() - captured).total_seconds() > 120:
                    raise IntelligenceError(409, "investigation_snapshot_expired")
                # Sidecar only. Do not modify Incident.analysis, plan, approval or state.
                tx.put_state("investigation:" + identity, document)

        await asyncio.to_thread(save)
        return document

    def investigation(self, identity: str) -> dict[str, object]:
        incident = self.incident_snapshot(identity)
        with self.repo.transaction() as tx:
            document = tx.get_state("investigation:" + identity)
        if document is None:
            raise IntelligenceError(404, "no_investigation")
        return {
            **document,
            "matches_incident_revision": document["incident_revision"] == revision(incident),
            "note": "Historical snapshot; inspect captured_at and per-source freshness. No execution authority.",
        }

    async def close(self) -> None:
        await self.provider.close()
