from __future__ import annotations

from datetime import timedelta

from incidents_service.config import Settings
from incidents_service.engine import ReliabilityLoop
from incidents_service.models import Analysis, Incident, Plan, now
from incidents_service.repository import Repository


def test_fault_onset_is_required_for_research_mttr_and_mttd() -> None:
    repo = Repository("sqlite:///:memory:")
    created = now() - timedelta(minutes=5)
    item = Incident(
        id="timing",
        service="catalog-service",
        environment="dev",
        title="Closed simulation fixture",
        status="closed",
        created_at=created,
        resolved_at=created + timedelta(seconds=90),
        detected_event_at=created - timedelta(seconds=2),
        signals=[],
        evidence_ids=[],
        analysis=Analysis(summary="Fixture", confidence="low", evidence_ids=[]),
        plan=Plan(action="escalate", target="catalog-service", reason="Fixture", risk="high"),
        audit=[],
    )
    loop = ReliabilityLoop(repo, Settings(dev_mode=True))
    with repo.transaction() as tx:
        tx.save_incident(item)
    report = loop.postmortem(item.id)
    assert report["mttr_seconds"] is None
    assert report["mttd_seconds"] is None
    assert report["incident_duration_seconds"] == 90
    assert report["detection_event_lag_seconds"] == 2
    assert report["simulation"] is True
    item.fault_started_at = created - timedelta(seconds=10)
    with repo.transaction() as tx:
        tx.save_incident(item)
    report = loop.postmortem(item.id)
    assert report["mttr_seconds"] == 100
    assert report["mttd_seconds"] == 10
    assert report["incident_duration_seconds"] == 90
    # A bad future onset must not be silently clamped to a successful zero.
    item.fault_started_at = created + timedelta(minutes=10)
    with repo.transaction() as tx:
        tx.save_incident(item)
    report = loop.postmortem(item.id)
    assert report["mttr_seconds"] is report["mttd_seconds"] is None
    assert report["timing_caveats"]
    repo.close()


def test_unknown_naive_or_negative_intervals_are_not_measured_zeros() -> None:
    clock = now()
    assert ReliabilityLoop._duration(None, clock) is None
    assert ReliabilityLoop._duration(clock, None) is None
    assert ReliabilityLoop._duration(clock.replace(tzinfo=None), clock) is None
    assert ReliabilityLoop._duration(clock, clock - timedelta(seconds=1)) is None
    assert ReliabilityLoop._duration(clock, clock) == 0
