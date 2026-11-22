"""Transactional incident lifecycle and policy-governed reliability loop."""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from incidents_service import deployment_intelligence as deploy_intel
from incidents_service.config import Settings
from incidents_service.detection import detect, upper_bound_metric
from incidents_service.execution import Executor
from incidents_service.models import Audit, Decision, Event, Incident, Metric, Signal, now
from incidents_service.policy import Policy, evaluate
from incidents_service.reasoning import analyze
from incidents_service.repository import Repository, Transaction


class DomainError(ValueError):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


class ReliabilityLoop:
    def __init__(self, repo: Repository, settings: Settings):
        self.repo, self.settings = repo, settings
        self.executor = Executor(settings)
        self.policy = Policy.load(settings.policy_path)

    def _get(self, tx: Transaction, incident_id: str) -> Incident:
        incident = tx.incident(incident_id)
        if incident is None:
            raise DomainError("Unknown incident", 404)
        return incident

    def _audit(
        self, tx: Transaction, incident: Incident, action: str, actor: str, detail: str
    ) -> None:
        entry = Audit(action=action, actor=actor, detail=detail)
        incident.audit.append(entry)
        incident.updated_at = entry.at
        tx.append_audit(
            incident.id,
            entry.model_dump(mode="json"),
            service=incident.service,
            environment=incident.environment,
        )

    def _emit(self, tx: Transaction, incident: Incident, kind: str) -> None:
        tx.emit(
            {
                "id": f"evt_{uuid.uuid4().hex}",
                "schema_version": "0.2",
                "timestamp": now().isoformat(),
                "source": "policy" if kind == "remediation" else "ai",
                "type": kind,
                "service": incident.service,
                "environment": incident.environment,
                "severity": incident.severity,
                "payload": {
                    "incident_id": incident.id,
                    "status": incident.status,
                    "action": incident.plan.action,
                    "evidence_ids": incident.evidence_ids,
                },
            }
        )

    def ingest(self, event: Event) -> dict[str, Any]:
        event.timestamp = event.timestamp.astimezone(UTC)
        with self.repo.transaction() as tx:
            previous = tx.event(event.id)
            if previous is not None:
                if previous != event.model_dump(mode="json"):
                    raise DomainError("Event id already exists with different content")
                return {"event_id": event.id, "duplicate": True, "incident_id": None}
            normal = False
            signal: Signal | None = None
            ready = False
            window_start = event.timestamp
            if event.type == "metric":
                metric = Metric.model_validate(event.payload)
                latest = tx.latest_sample(event.series())
                if latest and event.timestamp <= datetime.fromisoformat(str(latest["timestamp"])):
                    raise DomainError(
                        "Metric samples must have increasing producer timestamps per series"
                    )
                preceding = tx.baseline_samples(event.series())
                history = [value for _, value in preceding]
                if preceding:
                    window_start = datetime.fromisoformat(preceding[0][0])
                verdict = detect(
                    history, metric.value, two_sided=not upper_bound_metric(metric.name)
                )
                normal, ready = not verdict.anomalous, verdict.ready
                if verdict.anomalous:
                    signal = Signal(
                        series=event.series(),
                        metric=metric.name,
                        labels=metric.labels,
                        unit=metric.unit,
                        event_id=event.id,
                        observed=metric.value,
                        baseline_mean=verdict.mean,
                        baseline_std=verdict.std,
                        z_score=verdict.z_score,
                        isolation_score=verdict.isolation_score,
                    )
            tx.add_event(event, normal=normal)
            if event.type == "deployment":
                try:
                    deploy_intel.register(tx, event)
                except deploy_intel.DeploymentConflict as exc:
                    raise DomainError(str(exc)) from exc
            active = tx.active_incident(event.service, event.environment)
            if signal is not None:
                active = self._on_anomaly(tx, event, signal, active, window_start)
            elif active and active.status == "verifying" and event.type in {"metric", "health"}:
                self._verify(tx, active, event)
            if active:
                tx.save_incident(active)
            deploy_intel.observe(tx, event, signal, ready, active.id if active else None)
            return {
                "event_id": event.id,
                "duplicate": False,
                "baseline_ready": ready,
                "anomalous": signal is not None,
                "incident_id": active.id if active else None,
            }

    def _on_anomaly(
        self,
        tx: Transaction,
        event: Event,
        signal: Signal,
        active: Incident | None,
        window_start: datetime,
    ) -> Incident:
        if active is not None:
            # Baseline is frozen in each signal, including throughout recovery.
            old = next((s for s in active.signals if s.series == signal.series), None)
            if old:
                old.observed, old.event_id, old.recovered_samples = (
                    signal.observed,
                    signal.event_id,
                    0,
                )
            else:
                active.signals.append(signal)
                active.approval, active.approved_by = "pending", None
            active.evidence_ids = list(dict.fromkeys([*active.evidence_ids, event.id]))[-200:]
            if active.status == "verifying":
                self._audit(
                    tx,
                    active,
                    "recovery.not_recovered",
                    "system",
                    "Anomalous telemetry persists; deadline still applies",
                )
                return active
            if active.status == "remediating":
                return active
        evidence = tx.recent_events(event.service, event.environment, limit=200)
        signals = active.signals if active else [signal]
        analysis, plan, correlation = analyze(event, signals, evidence)
        # Capacity plans without replicas remain recommendations until an explicit
        # live plan-preparation pass outside this ingest transaction supplies them.
        rule = self.policy.rules.get(plan.action)
        if rule:
            plan.risk, plan.requires_approval, plan.policy_version = (
                rule.risk,
                rule.requires_approval,
                self.policy.version,
            )
        plan.executor = self.settings.executor
        if active is None:
            active = Incident(
                id=f"inc_{now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:10]}",
                service=event.service,
                environment=event.environment,
                title=f"Unusual {signal.metric} on {event.service}",
                severity="critical" if abs(signal.z_score) >= 10 else "warning",
                signals=signals,
                evidence_ids=analysis.evidence_ids,
                analysis=analysis,
                plan=plan,
                audit=[],
                change_correlation=correlation,
                detected_event_at=event.timestamp,
            )
            self._audit(
                tx,
                active,
                "incident.open",
                "detector",
                "Isolation Forest/statistical baseline anomaly",
            )
            active.status = "investigating"
            self._audit(tx, active, "incident.investigating", "reasoner", analysis.summary)
        else:
            if active.plan != plan:
                active.approval, active.approved_by = "pending", None
                self._audit(
                    tx, active, "approval.invalidated", "system", "Plan changed with new evidence"
                )
            active.analysis, active.plan, active.change_correlation = analysis, plan, correlation
            active.evidence_ids = list(
                dict.fromkeys([*active.evidence_ids, *analysis.evidence_ids])
            )[-200:]
            self._audit(
                tx, active, "incident.evidence", "detector", f"Additional anomaly: {event.id}"
            )
        tx.emit(
            {
                "id": f"anomaly_{event.id}",
                "schema_version": "0.2",
                "timestamp": event.timestamp.isoformat(),
                "source": "ml",
                "type": "anomaly",
                "service": event.service,
                "environment": event.environment,
                "severity": active.severity,
                "payload": {
                    "metric": signal.metric,
                    "labels": signal.labels,
                    "score": 1 - math.exp(-abs(signal.z_score) / 4),
                    "threshold": 0.63,
                    "model": signal.model,
                    "window": {
                        "start": window_start.isoformat(),
                        "end": event.timestamp.isoformat(),
                    },
                    "baseline": {"mean": signal.baseline_mean, "std": signal.baseline_std},
                },
            }
        )
        self._emit(tx, active, "incident")
        return active

    def decide(
        self,
        incident_id: str,
        decision: Literal["approved", "rejected", "deferred"],
        body: Decision,
    ) -> Incident:
        with self.repo.transaction() as tx:
            incident = self._get(tx, incident_id)
            if incident.status != "investigating":
                raise DomainError("Only an investigating incident accepts approval decisions")
            incident.approval, incident.approved_by = (
                decision,
                body.actor if decision == "approved" else None,
            )
            if decision == "rejected":
                incident.status = "escalated"
            self._audit(tx, incident, f"remediation.{decision}", body.actor, body.note)
            tx.save_incident(incident)
            return incident

    def execute(self, incident_id: str, actor: str, *, automatic_only: bool = False) -> Incident:
        # Live preflight must not hold the decision lock or delay the kill switch.
        with self.repo.transaction() as tx:
            observed = self._get(tx, incident_id)
            preflight_mode = tx.get_state("autonomy", {"mode": "recommend"})["mode"]
        context: dict[str, Any] = {}
        context_error = False
        if preflight_mode == "auto-safe" and observed.approval != "approved":
            try:
                context = self.executor.policy_context(observed.plan)
            except Exception:
                context_error = True
        target_uid = context.pop("target_uid", None)
        template_digest = context.pop("target_template_digest", None)
        live_revision = context.pop("live_revision", None)
        with self.repo.transaction() as tx:
            incident = self._get(tx, incident_id)
            mode = str(tx.get_state("autonomy", {"mode": "recommend"})["mode"])
            if observed.plan != incident.plan or observed.updated_at != incident.updated_at:
                context, context_error = {}, True
            if automatic_only and (
                incident.approval != "pending"
                or not 0 <= (now() - incident.updated_at).total_seconds() <= 60
            ):
                return incident
            if incident.plan.action == "rollback" and live_revision is not None:
                from incidents_service.rollback_context import context as rollback_context

                observed_context = rollback_context(tx, incident, live_revision)
                if not observed_context:
                    context_error = True
                context.update(observed_context)
            plan_filled = False
            if (
                not context_error
                and mode == "auto-safe"
                and incident.approval == "pending"
                and incident.plan.action == "scale"
                and incident.plan.replicas is None
                and isinstance(context.get("current_replicas"), int)
            ):
                incident.plan.replicas = int(context["current_replicas"]) + 1
                plan_filled = True
            if (
                not context_error
                and incident.plan.action == "rollback"
                and context.get("rollout_bad") is True
                and template_digest
                and self.policy.rules.get("rollback") is not None
                and self.policy.rules["rollback"].risk == "low"
                and mode == "auto-safe"
                and incident.approval == "pending"
            ):
                incident.plan.risk = "low"
                incident.plan.reversible = True
                self._audit(
                    tx,
                    incident,
                    "plan.live_preconditions",
                    "policy",
                    "Explicit low-risk rollback policy and complete observed image-only prerequisites",
                )
            history: list[dict[str, str]] = tx.get_state("executions", [])
            recent = [
                x
                for x in history
                if (now() - datetime.fromisoformat(x["at"])).total_seconds() < 3600
            ]
            per_target = [x for x in recent if x["target"] == incident.service]
            elapsed = (
                (now() - datetime.fromisoformat(per_target[-1]["at"])).total_seconds()
                if per_target
                else math.inf
            )
            verdict = evaluate(
                self.policy,
                incident,
                mode,
                actions_in_hour=len(recent),
                incident_actions=sum(
                    1 for a in incident.audit if a.action == "remediation.started"
                ),
                seconds_since_target_action=elapsed,
                target_allowed=(
                    incident.service in self.settings.allowed_targets
                    and incident.plan.target == incident.service
                    and incident.environment == self.settings.environment
                    and not context_error
                ),
                **context,
            )
            if automatic_only and (
                not verdict.automatic or (now() - observed.updated_at).total_seconds() > 60
            ):
                return incident
            if not verdict.allowed:
                tx.append_audit(
                    incident.id,
                    Audit(
                        action="remediation.denied", actor=actor, detail=verdict.reason
                    ).model_dump(mode="json"),
                    service=incident.service,
                    environment=incident.environment,
                )
                # A denial is a recorded result, not an exception that rolls the audit back.
                return incident.model_copy(update={"execution_output": f"DENIED: {verdict.reason}"})
            if plan_filled:
                self._audit(
                    tx,
                    incident,
                    "plan.live_preconditions",
                    "policy",
                    "One-replica scale-up filled from live managed deployment",
                )
            incident.status = "remediating"
            incident.executed_at = now()
            incident.verification_deadline = now() + timedelta(
                seconds=self.policy.verification_seconds
            )
            self._audit(
                tx,
                incident,
                "remediation.started",
                "policy:auto" if verdict.automatic else actor,
                f"{incident.plan.action}; policy {self.policy.version}; {self.settings.executor}",
            )
            recent.append(
                {"at": now().isoformat(), "target": incident.service, "incident_id": incident.id}
            )
            tx.put_state("executions", recent)
            tx.save_incident(incident)
        # External I/O is outside the transaction. The persisted started state prevents
        # duplicate execution and is escalated, never retried, after an interrupted run.
        try:
            with self.repo.transaction() as tx:
                dispatch_mode = tx.get_state("autonomy", {"mode": "recommend"})["mode"]
                if dispatch_mode == "observe" or (
                    verdict.automatic and dispatch_mode != "auto-safe"
                ):
                    raise DomainError("Kill switch enabled before execution")

            def dispatch_allowed() -> bool:
                with self.repo.transaction() as tx:
                    current = tx.incident(incident_id)
                    return bool(
                        tx.get_state("autonomy", {"mode": "recommend"})["mode"] == "auto-safe"
                        and current is not None
                        and current.status == "remediating"
                        and current.plan == incident.plan
                    )

            result = (
                self.executor.run(
                    incident.plan,
                    automatic=True,
                    expected_uid=target_uid,
                    expected_template_digest=template_digest,
                    expected_revision=live_revision,
                    dispatch_allowed=dispatch_allowed,
                )
                if verdict.automatic
                else self.executor.run(incident.plan)
            )
        except Exception as exc:
            with self.repo.transaction() as tx:
                incident = self._get(tx, incident_id)
                incident.status = "escalated"
                incident.execution_output = (
                    f"Execution failed or uncertain ({type(exc).__name__}); do not blindly retry"
                )
                self._audit(
                    tx, incident, "remediation.failed", "executor", incident.execution_output
                )
                tx.save_incident(incident)
            return incident
        with self.repo.transaction() as tx:
            incident = self._get(tx, incident_id)
            incident.status, incident.execution_output, incident.undo = (
                "verifying",
                result.output,
                result.undo,
            )
            for signal in incident.signals:
                signal.recovered_samples = 0
            self._audit(tx, incident, "remediation.completed", "executor", result.output)
            self._emit(tx, incident, "remediation")
            tx.save_incident(incident)
            return incident

    def run_automatic(self) -> int:
        """Bounded worker sweep, no approved/manual action is executed here.

        Each candidate re-enters the transaction lock and rechecks mode, policy,
        rate limits and current state. Denied candidates do not flood the audit.
        """
        with self.repo.transaction() as tx:
            if tx.get_state("autonomy", {"mode": "recommend"})["mode"] != "auto-safe":
                return 0
            candidates = [
                item.id
                for item in tx.list_incidents(limit=100)
                if item.status == "investigating"
                and item.approval == "pending"
                and item.service in self.settings.allowed_targets
                and item.environment == self.settings.environment
                and 0 <= (now() - item.updated_at).total_seconds() <= 60
            ]
        executed = 0
        for incident_id in candidates:
            item = self.execute(incident_id, "policy:auto", automatic_only=True)
            executed += int(item.status in {"verifying", "escalated"})
        return executed

    def _verify(self, tx: Transaction, incident: Incident, event: Event) -> None:
        if (
            incident.executed_at is None
            or event.timestamp <= incident.executed_at
            or event.timestamp > now() + timedelta(seconds=1)
        ):
            return
        if event.type == "metric":
            matching = next((s for s in incident.signals if s.series == event.series()), None)
            if matching:
                value = Metric.model_validate(event.payload).value
                scale = max(matching.baseline_std, abs(matching.baseline_mean) * 0.05, 0.001)
                delta = (value - matching.baseline_mean) / scale
                healthy = abs(delta) < 2 if not upper_bound_metric(matching.metric) else delta < 2
                matching.recovered_samples = matching.recovered_samples + 1 if healthy else 0
        samples_good = all(
            s.recovered_samples >= self.policy.recovery_samples for s in incident.signals
        )
        health_events = tx.recent_events(incident.service, incident.environment, "health", 1)
        health_good = False
        if health_events:
            latest = health_events[0]
            ts = datetime.fromisoformat(str(latest["timestamp"]))
            checks = latest["payload"]
            health_good = (
                ts > incident.executed_at
                and 0 <= (now() - ts).total_seconds() <= 60
                and checks.get("status") == "healthy"
                and checks.get("slo_ok") is True
                and checks.get("errors_ok") is True
                and checks.get("latency_ok") is True
            )
        if samples_good and health_good:
            incident.status, incident.resolved_at = "closed", now()
            self._audit(
                tx,
                incident,
                "incident.closed",
                "verifier",
                "All affected series recovered; fresh health, error, latency and SLO checks passed",
            )
            self._emit(tx, incident, "incident")

    def sweep(self, *, recover_interrupted: bool = False) -> None:
        with self.repo.transaction() as tx:
            deploy_intel.finalize(tx)
            for incident in tx.list_incidents(limit=10000):
                reason = None
                if recover_interrupted and incident.status == "remediating":
                    reason = "Process restarted during execution; effect uncertain, operator reconciliation required"
                elif (
                    incident.status == "verifying"
                    and incident.verification_deadline
                    and now() > incident.verification_deadline
                ):
                    reason = "Recovery deadline elapsed without all required fresh checks"
                if reason:
                    incident.status = "escalated"
                    self._audit(tx, incident, "incident.escalated", "verifier", reason)
                    tx.save_incident(incident)

    def set_mode(self, mode: Literal["observe", "recommend", "auto-safe"], actor: str) -> None:
        with self.repo.transaction() as tx:
            tx.put_state("autonomy", {"mode": mode})
            tx.append_audit(
                None,
                Audit(action="autonomy.mode.set", actor=actor, detail=mode).model_dump(mode="json"),
                environment=self.settings.environment,
            )

    @staticmethod
    def _duration(start: datetime | None, end: datetime | None) -> float | None:
        if start is None or end is None or start.tzinfo is None or end.tzinfo is None:
            return None
        seconds = (end - start).total_seconds()
        return seconds if seconds >= 0 else None

    def postmortem(self, incident_id: str) -> dict[str, Any]:
        with self.repo.transaction() as tx:
            incident = self._get(tx, incident_id)
            if incident.status != "closed":
                raise DomainError("Postmortem is available only after verified closure")
            return {
                "incident": incident.model_dump(mode="json"),
                "mttd_seconds": self._duration(incident.fault_started_at, incident.created_at),
                "detection_event_lag_seconds": self._duration(
                    incident.detected_event_at, incident.created_at
                ),
                "mttr_seconds": self._duration(incident.fault_started_at, incident.resolved_at),
                "incident_duration_seconds": self._duration(
                    incident.created_at, incident.resolved_at
                ),
                "timing_caveats": [
                    "Fault-onset MTTD/MTTR require recorded ground-truth onset and valid aware timestamp order; missing or invalid intervals are null. Incident duration is not research MTTR."
                ],
                "lessons": [
                    "Confirm the probable cause with an operator",
                    "Add a regression test for the triggering failure",
                ],
                "simulation": incident.plan.executor == "simulation",
            }
