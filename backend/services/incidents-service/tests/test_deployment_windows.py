from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from incidents_service import deployment_intelligence as di
from incidents_service.config import Settings
from incidents_service.engine import DomainError, ReliabilityLoop
from incidents_service.main import create_app
from incidents_service.models import Event, now
from incidents_service.repository import Repository
from telemetry import EventEnvelope


def deploy(
    identity: str,
    start: datetime,
    *,
    logical: str | None = "release-a",
    revision: str = "v2",
    phase: str = "succeeded",
    service: str = "catalog-service",
    environment: str = "dev",
    explicit_start: bool = True,
) -> Event:
    payload: dict[str, Any] = {
        "action": "deploy",
        "revision": revision,
        "previous_revision": "v1",
        "triggered_by": "unit-fixture",
        "status": phase,
    }
    if logical is not None:
        payload["deployment_id"] = logical
    if explicit_start:
        payload["started_at"] = start.isoformat()
    return Event(
        id=identity,
        timestamp=start,
        source="deployment",
        type="deployment",
        service=service,
        environment=environment,
        payload=payload,
    )


def metric(
    identity: str,
    at: datetime,
    value: float,
    *,
    name: str = "latency_p95",
    labels: dict[str, str] | None = None,
) -> Event:
    return Event(
        id=identity,
        timestamp=at,
        source="prometheus",
        type="metric",
        service="catalog-service",
        payload={
            "name": name,
            "labels": labels or {},
            "value": value,
            "unit": "ratio" if name == "error_rate" else "seconds",
        },
    )


def health(at: datetime, good: bool = True) -> Event:
    return Event(
        id="health-" + at.isoformat(),
        timestamp=at,
        source="registry",
        type="health",
        service="catalog-service",
        payload={
            "status": "healthy" if good else "unhealthy",
            "slo_ok": good,
            "errors_ok": good,
            "latency_ok": good,
        },
    )


def loop(repo: Repository) -> ReliabilityLoop:
    return ReliabilityLoop(repo, Settings(dev_mode=True, allowed_targets=["catalog-service"]))


def state(repo: Repository) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    with repo.transaction() as tx:
        return tx.list_rollouts(service="catalog-service", environment="dev"), di.summary(
            tx, service="catalog-service", environment="dev", since=now() - timedelta(days=1)
        )


def good_observations(
    repo: Repository, start: datetime, *, qualified: bool = True, healthy: bool = True
) -> None:
    # Explicit synthetic unit evidence, not a real workload acceptance run.
    with repo.transaction() as tx:
        for index, seconds in enumerate((145, 160, 175)):
            for name in ("latency_p95", "error_rate"):
                di.observe(
                    tx,
                    metric(name + str(index), start + timedelta(seconds=seconds), 0.01, name=name),
                    None,
                    qualified,
                    None,
                )
        di.observe(tx, health(start + timedelta(seconds=175), healthy), None, False, None)
        di.finalize(tx, start + timedelta(seconds=196))


def test_lifecycle_identity_is_not_revision_and_duplicate_ingest_is_idempotent() -> None:
    repo = Repository("sqlite:///:memory:")
    runtime = loop(repo)
    start = now() - timedelta(seconds=600)
    first = deploy("start", start, phase="in_progress")
    runtime.ingest(first)
    final = deploy("finish", start)
    final.timestamp += timedelta(seconds=20)
    runtime.ingest(final)
    assert runtime.ingest(final)["duplicate"]
    rows, report = state(repo)
    assert len(rows) == 1 and rows[0]["phase"] == "succeeded"
    assert rows[0]["source_event_ids"] == ["start", "finish"]
    assert report["identified_deployments"] == 1 and report["change_failure_rate"] is None
    runtime.ingest(deploy("another", start + timedelta(seconds=400), logical="release-b"))
    assert len(state(repo)[0]) == 2
    repo.close()


@pytest.mark.parametrize("changed", ["revision", "started_at", "status"])
def test_conflicting_lifecycle_is_rejected_transactionally(changed: str) -> None:
    repo = Repository("sqlite:///:memory:")
    runtime = loop(repo)
    start = now() - timedelta(seconds=600)
    runtime.ingest(deploy("first", start))
    item = deploy("conflict", start)
    item.payload[changed] = {
        "revision": "other",
        "started_at": (start - timedelta(seconds=1)).isoformat(),
        "status": "failed",
    }[changed]
    with pytest.raises(DomainError):
        runtime.ingest(item)
    with repo.transaction() as tx:
        assert tx.event("conflict") is None
    assert state(repo)[0][0]["phase"] == "succeeded"
    repo.close()


def test_real_detector_marks_bad_window_once_with_current_flag_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = Repository("sqlite:///:memory:")
    runtime = loop(repo)
    start = now() - timedelta(seconds=300)
    for index in range(12):
        runtime.ingest(
            metric("warm-" + str(index), start - timedelta(seconds=120 - index * 5), 0.1)
        )
    runtime.ingest(deploy("deployment", start))
    clock = start + timedelta(seconds=80)
    monkeypatch.setattr(di, "now", lambda: clock)
    result = runtime.ingest(metric("bad", start + timedelta(seconds=15), 9))
    runtime.ingest(metric("also-bad", start + timedelta(seconds=30), 8))
    rows, report = state(repo)
    assert rows[0]["outcome"] == "bad" and rows[0]["flag_latency_seconds"] == 80
    assert rows[0]["bad_observed_at"] != rows[0]["flagged_at"]
    assert rows[0]["incident_id"] == result["incident_id"]
    assert report["change_failure_rate"] == 1
    with repo.transaction() as tx:
        emitted = [doc for _, doc in tx.pending(1000) if doc["type"] == "rollout.bad"]
    assert len(emitted) == 1
    envelope = EventEnvelope.model_validate(emitted[0])
    assert (
        envelope.payload["authorizes_execution"] is False
        and envelope.payload["causation_proven"] is False
    )
    repo.close()


@pytest.mark.parametrize("qualified,healthy", [(False, True), (True, False)])
def test_missing_baseline_or_health_is_not_a_healthy_rollout(
    qualified: bool, healthy: bool
) -> None:
    repo = Repository("sqlite:///:memory:")
    start = now() - timedelta(seconds=600)
    loop(repo).ingest(deploy("d", start))
    good_observations(repo, start, qualified=qualified, healthy=healthy)
    rows, report = state(repo)
    assert rows[0]["outcome"] == "insufficient"
    assert report["change_failure_rate"] is None and report["unknown_outcomes"] == 1
    repo.close()


def test_fresh_end_window_samples_and_health_can_observe_a_healthy_outcome() -> None:
    repo = Repository("sqlite:///:memory:")
    start = now() - timedelta(seconds=600)
    loop(repo).ingest(deploy("d", start))
    good_observations(repo, start)
    rows, report = state(repo)
    assert rows[0]["outcome"] == "healthy"
    assert report["change_failure_rate"] == 0 and report["outcome_coverage"] == 1
    repo.close()


def test_unknown_missing_identity_and_unmapped_old_events_keep_cfr_null() -> None:
    repo = Repository("sqlite:///:memory:")
    start = now() - timedelta(seconds=600)
    runtime = loop(repo)
    runtime.ingest(deploy("known-bad", start, phase="failed"))
    runtime.ingest(deploy("legacy", start + timedelta(seconds=200), logical=None, phase="failed"))
    with repo.transaction() as tx:
        tx.add_event(deploy("old-unmapped", start + timedelta(seconds=400), logical=None))
    _, report = state(repo)
    assert report["identified_deployments"] == 1 and report["confirmed_bad"] == 1
    assert report["unidentified_or_unmapped_events"] == 2
    assert report["change_failure_rate"] is None
    assert report["observed_finalized_rate"] == 1
    repo.close()


def test_scope_and_identity_namespaces_do_not_merge_or_contaminate() -> None:
    repo = Repository("sqlite:///:memory:")
    runtime = loop(repo)
    start = now() - timedelta(seconds=600)
    runtime.ingest(deploy("event-x", start, logical=None))
    runtime.ingest(deploy("event-y", start + timedelta(seconds=200), logical="event-x"))
    runtime.ingest(deploy("other-env", start, environment="prod", phase="failed"))
    runtime.ingest(deploy("other-service", start, service="cart-service", phase="failed"))
    rows, report = state(repo)
    assert len(rows) == 2 and report["confirmed_bad"] == 0 and report["identified_deployments"] == 1
    repo.close()


def test_overlaps_are_unknown_even_when_previously_observed_bad() -> None:
    repo = Repository("sqlite:///:memory:")
    runtime = loop(repo)
    start = now() - timedelta(seconds=600)
    runtime.ingest(deploy("one", start))
    with repo.transaction() as tx:
        row = di.Rollout.model_validate(tx.list_rollouts()[0])
        di._bad(
            tx,
            row,
            metric("synthetic-anomaly", start + timedelta(seconds=10), 9),
            "Synthetic unit signal",
            None,
        )
        di._save(tx, row)
    runtime.ingest(deploy("two", start + timedelta(seconds=15), logical="second", revision="v3"))
    rows, report = state(repo)
    assert all(row["ambiguous"] for row in rows)
    assert (
        report["confirmed_bad"] == 0
        and report["unknown_outcomes"] == 2
        and report["change_failure_rate"] is None
    )
    repo.close()


def test_window_expiry_and_late_observation_do_not_fabricate_health() -> None:
    repo = Repository("sqlite:///:memory:")
    start = now() - timedelta(seconds=600)
    runtime = loop(repo)
    runtime.ingest(deploy("d", start))
    with repo.transaction() as tx:
        di.observe(tx, health(start + timedelta(seconds=300)), None, False, None)
        di.finalize(tx, start + timedelta(seconds=196))
    assert state(repo)[0][0]["outcome"] == "insufficient"
    repo.close()


def test_unreported_start_does_not_fabricate_flag_latency() -> None:
    repo = Repository("sqlite:///:memory:")
    loop(repo).ingest(
        deploy("d", now() - timedelta(seconds=300), phase="failed", explicit_start=False)
    )
    row = state(repo)[0][0]
    assert row["anchor_source"] == "first_event_timestamp" and row["flag_latency_seconds"] is None
    repo.close()


def test_rollout_and_event_mapping_survive_repository_reopen(tmp_path: Path) -> None:
    url = "sqlite:///" + str(tmp_path / "rollouts.db")
    repo = Repository(url)
    loop(repo).ingest(deploy("d", now() - timedelta(seconds=300), phase="failed"))
    repo.close()
    repo = Repository(url)
    rows, report = state(repo)
    assert (
        len(rows) == 1
        and report["change_failure_rate"] == 1
        and report["unidentified_or_unmapped_events"] == 0
    )
    repo.close()


def test_authenticated_analytics_api_validates_scope_and_aware_windows() -> None:
    repo = Repository("sqlite:///:memory:")
    config = Settings(api_token="analytics-fixture", allowed_targets=["catalog-service"])
    app = create_app(config, repo)
    with TestClient(app) as http:
        assert (
            http.get("/deployment-intelligence/summary?service=catalog-service").status_code == 401
        )
        auth = {"Authorization": "Bearer analytics-fixture"}
        assert (
            http.get("/deployment-intelligence/summary?service=other", headers=auth).status_code
            == 422
        )
        assert (
            http.get(
                "/deployment-intelligence/summary?service=catalog-service&since=2026-11-22T00:00:00",
                headers=auth,
            ).status_code
            == 422
        )
        result = http.get("/deployment-intelligence/summary?service=catalog-service", headers=auth)
        assert result.status_code == 200 and result.json()["change_failure_rate"] is None
        assert (
            http.get(
                "/deployment-intelligence/rollouts?service=catalog-service", headers=auth
            ).json()["rollouts"]
            == []
        )
    repo.close()


def test_previous_revision_can_be_filled_but_not_erased_or_rewritten() -> None:
    repo = Repository("sqlite:///:memory:")
    runtime = loop(repo)
    start = now() - timedelta(seconds=10)
    first = deploy("missing-previous", start, phase="in_progress")
    first.payload.pop("previous_revision")
    runtime.ingest(first)
    runtime.ingest(deploy("known-previous", start, phase="in_progress"))
    omitted = deploy("omitted-later", start, phase="in_progress")
    omitted.payload.pop("previous_revision")
    runtime.ingest(omitted)
    assert state(repo)[0][0]["previous_revision"] == "v1"
    conflict = deploy("rewritten-previous", start, phase="in_progress")
    conflict.payload["previous_revision"] = "v-other"
    with pytest.raises(DomainError):
        runtime.ingest(conflict)
    assert state(repo)[0][0]["previous_revision"] == "v1"


def test_late_unhealthy_evidence_cannot_leave_a_finalized_healthy_result() -> None:
    repo = Repository("sqlite:///:memory:")
    start = now() - timedelta(seconds=300)
    loop(repo).ingest(deploy("late-health", start))
    good_observations(repo, start)
    assert state(repo)[0][0]["outcome"] == "healthy"
    with repo.transaction() as tx:
        di.observe(tx, health(start + timedelta(seconds=178), False), None, False, None)
        di.finalize(tx, start + timedelta(seconds=200))
    assert state(repo)[0][0]["outcome"] == "insufficient"


def test_producer_can_confirm_a_previously_implicit_matching_start() -> None:
    repo = Repository("sqlite:///:memory:")
    runtime = loop(repo)
    start = now() - timedelta(seconds=300)
    runtime.ingest(deploy("implicit-start", start, explicit_start=False))
    runtime.ingest(deploy("confirmed-start", start))
    good_observations(repo, start)
    assert state(repo)[0][0]["outcome"] == "healthy"


def test_summary_does_not_count_future_identified_or_unmapped_deployments() -> None:
    repo = Repository("sqlite:///:memory:")
    runtime = loop(repo)
    point = now()
    runtime.ingest(
        deploy("already-failed", point - timedelta(seconds=600), phase="failed", logical="past")
    )
    runtime.ingest(
        deploy("future-failed", point + timedelta(seconds=30), phase="failed", logical="future")
    )
    with repo.transaction() as tx:
        tx.add_event(deploy("future-unmapped", point + timedelta(seconds=40), logical=None))
        report = di.summary(
            tx, service="catalog-service", environment="dev", since=point - timedelta(days=1)
        )
    assert report["identified_deployments"] == report["confirmed_bad"] == 1
    assert report["unidentified_or_unmapped_events"] == 0
    assert report["change_failure_rate"] == 1
    assert datetime.fromisoformat(report["as_of"]) >= point
    repo.close()
