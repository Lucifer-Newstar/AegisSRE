from __future__ import annotations

import os
import uuid
from datetime import timedelta

import pytest
from incidents_service import deployment_intelligence as di
from incidents_service.config import Settings
from incidents_service.engine import ReliabilityLoop
from incidents_service.models import Event, now
from incidents_service.repository import Repository, audit, events, outbox, rollout_events, rollouts
from sqlalchemy import delete, select


@pytest.mark.skipif(
    not os.environ.get("AEGIS_TEST_DATABASE_URL"), reason="Requires isolated actual PostgreSQL"
)
def test_actual_postgres_rollout_identity_window_counts_and_reopen() -> None:
    url = os.environ["AEGIS_TEST_DATABASE_URL"]
    service = "ci-rollout-" + uuid.uuid4().hex[:12]
    repo = Repository(url)
    start = now() - timedelta(seconds=600)

    def event(identity: str, seconds: int, logical: str, phase: str) -> Event:
        at = start + timedelta(seconds=seconds)
        return Event(
            id=identity + service,
            timestamp=at,
            source="deployment",
            type="deployment",
            service=service,
            payload={
                "deployment_id": logical,
                "started_at": at.isoformat(),
                "action": "deploy",
                "revision": "v2",
                "status": phase,
                "triggered_by": "postgres-ci-fixture",
            },
        )

    try:
        runtime = ReliabilityLoop(repo, Settings(dev_mode=True, allowed_targets=[service]))
        pending = event("pending", 0, "one", "in_progress")
        runtime.ingest(pending)
        terminal = event("terminal", 10, "one", "succeeded")
        terminal.payload["started_at"] = start.isoformat()
        runtime.ingest(terminal)
        failed = event("failed", 300, "two", "failed")
        runtime.ingest(failed)
        assert runtime.ingest(failed)["duplicate"]
        orphan = event("old-unmapped", 100, "unmapped", "in_progress")
        with repo.transaction() as tx:
            tx.add_event(orphan)
            report = di.summary(
                tx, service=service, environment="dev", since=start - timedelta(seconds=1)
            )
            assert report["identified_deployments"] == 2 and report["unknown_outcomes"] == 1
            assert report["confirmed_bad"] == 1 and report["unidentified_or_unmapped_events"] == 1
            assert report["change_failure_rate"] is None
        repo.close()
        repo = Repository(url)
        with repo.transaction() as tx:
            rows = tx.list_rollouts(service=service, environment="dev")
            assert len(rows) == 2
            report = di.summary(
                tx, service=service, environment="dev", since=start + timedelta(seconds=200)
            )
            assert report["identified_deployments"] == 1 and report["change_failure_rate"] == 1
            assert report["unidentified_or_unmapped_events"] == 0
    finally:
        with repo.transaction() as tx:
            ids = list(
                tx.conn.execute(
                    select(rollouts.c.id).where(rollouts.c.service == service)
                ).scalars()
            )
            tx.conn.execute(delete(rollout_events).where(rollout_events.c.rollout_id.in_(ids)))
            tx.conn.execute(delete(rollouts).where(rollouts.c.service == service))
            tx.conn.execute(delete(events).where(events.c.service == service))
            tx.conn.execute(
                delete(outbox).where(outbox.c.document["service"].as_string() == service)
            )
            tx.conn.execute(
                delete(audit).where(
                    audit.c.document["detail"]
                    .as_string()
                    .in_(["Observed bad deployment window: " + identity for identity in ids])
                )
            )
        repo.close()
