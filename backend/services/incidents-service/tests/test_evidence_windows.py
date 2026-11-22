from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta, timezone

from incidents_service.config import Settings
from incidents_service.evidence_tools import ReadOnlyTools, evidence_only
from incidents_service.intelligence import Intelligence
from incidents_service.knowledge import KnowledgeDocument, KnowledgeStore
from incidents_service.models import Analysis, Event, Incident, Plan, now
from incidents_service.repository import Repository, events
from sqlalchemy import update


def metric(identity: str, timestamp: datetime, value: float) -> Event:
    return Event(
        id=identity,
        source="prometheus",
        type="metric",
        service="catalog-service",
        timestamp=timestamp,
        payload={"name": "latency_seconds", "value": value},
    )


def test_old_offset_records_sort_and_filter_by_instant_without_migration() -> None:
    repo = Repository("sqlite:///:memory:")
    clock = now()
    older = metric("older", clock - timedelta(seconds=90), 1)
    newer = metric("newer", clock - timedelta(seconds=30), 2)
    offset = timezone(timedelta(hours=5, minutes=30))
    legacy = older.model_copy(update={"timestamp": older.timestamp.astimezone(offset)})
    with repo.transaction() as tx:
        tx.add_event(older, normal=True)
        tx.add_event(newer, normal=True)
        # A legacy non-UTC row, retained as-is, must not sort after a newer instant.
        tx.conn.execute(
            update(events)
            .where(events.c.id == older.id)
            .values(timestamp=legacy.timestamp.isoformat(), document=legacy.model_dump(mode="json"))
        )
        assert [item["id"] for item in tx.recent_events()] == ["newer", "older"]
        assert tx.baseline(newer.series()) == [1, 2]
        assert tx.latest_sample(newer.series())["id"] == "newer"  # type: ignore[index]
        assert [
            item["id"] for item in tx.recent_events(not_after=clock - timedelta(seconds=60))
        ] == ["older"]
        assert [
            item["id"] for item in tx.recent_events(not_before=clock - timedelta(seconds=60))
        ] == ["newer"]
    repo.close()


def test_historical_window_preserves_qualifying_metric_and_excludes_recovery() -> None:
    repo = Repository("sqlite:///:memory:")
    clock = now()
    anchor = clock - timedelta(days=1)
    with repo.transaction() as tx:
        tx.add_event(metric("qualifying", anchor, 5))
        for index in range(4):
            tx.add_event(metric(f"nearby-{index}", anchor + timedelta(seconds=index + 1), 0.8))
        tx.add_event(metric("recovery-now", clock, 0.1))
        tx.add_event(metric("too-old", anchor - timedelta(hours=1), 0.1))
        tx.add_event(
            Event(
                id="cause-after",
                type="log",
                source="loki",
                service="catalog-service",
                timestamp=anchor + timedelta(seconds=2),
                payload={"message": "Database unavailable", "level": "ERROR"},
            )
        )
        # Required IDs cannot smuggle another service/environment into the snapshot.
        tx.add_event(
            metric("other-scope", anchor, 4).model_copy(update={"service": "cart-service"})
        )
    reader = ReadOnlyTools(repo, None, allowed_targets=["catalog-service"], environment="dev")
    snapshot = reader.collect(
        "catalog-service",
        "latency?",
        incident_anchor=anchor,
        at=clock,
        required_event_ids=("qualifying", "other-scope"),
    )
    identities = {item.source_ref for item in snapshot.evidence}
    assert "qualifying" in identities and "cause-after" in identities
    assert not identities.intersection({"recovery-now", "too-old", "other-scope"})
    assert snapshot.temporal_scope == "incident_window"
    assert snapshot.evidence_anchor == anchor.isoformat()
    assert snapshot.captured_at == clock.isoformat()
    assert all(not item.stale for item in snapshot.evidence)
    assert "Historical evidence" in evidence_only(snapshot).summary
    payload = snapshot.provider_payload("investigate")
    assert payload["temporal_scope"] == "incident_window" and payload["window_end"]
    repo.close()


def test_historical_retrieval_excludes_self_future_cases_and_current_metadata() -> None:
    repo = Repository("sqlite:///:memory:")
    store = KnowledgeStore(repo)
    for identity, kind in (
        ("incident:self", "incident"),
        ("incident:earlier", "incident"),
        ("guide", "runbook"),
        ("metadata", "service"),
    ):
        store.upsert(
            KnowledgeDocument(
                id=identity,
                kind=kind,
                title="Database timeout",
                content="Database unavailable connection refused timeout",
                source="test:history",
            )
        )
    anchor = now()
    store.upsert(
        KnowledgeDocument(
            id="incident:future",
            kind="incident",
            title="Database timeout",
            content="Database unavailable connection refused timeout",
            source="test:future",
        )
    )
    results = store.search(
        "database timeout",
        service="catalog-service",
        environment="dev",
        limit=10,
        historical_at=anchor,
        excluded_document="incident:self",
    )
    assert {item["document_id"] for item in results} == {"incident:earlier", "guide"}
    repo.close()


def test_investigation_uses_detection_anchor_not_current_recovery() -> None:
    repo = Repository("sqlite:///:memory:")
    anchor = now() - timedelta(days=1)
    item = Incident(
        id="old-case",
        service="catalog-service",
        environment="dev",
        title="Historical incident",
        signals=[],
        evidence_ids=["qualifying"],
        analysis=Analysis(
            summary="UNVERIFIED_DIAGNOSIS_MUST_NOT_BECOME_QUESTION",
            confidence="low",
            evidence_ids=["qualifying"],
        ),
        plan=Plan(action="escalate", target="catalog-service", reason="Unknown", risk="high"),
        audit=[],
        created_at=anchor,
        detected_event_at=anchor,
    )
    with repo.transaction() as tx:
        tx.add_event(metric("qualifying", anchor, 5))
        tx.add_event(metric("healthy-now", now(), 0.1))
        tx.save_incident(item)
    agent = Intelligence(repo, Settings(dev_mode=True), None)
    result = asyncio.run(agent.investigate(item.id))
    snapshot = result["result"]["snapshot"]  # type: ignore[index]
    assert snapshot["temporal_scope"] == "incident_window"
    assert snapshot["evidence_anchor"] == anchor.astimezone(UTC).isoformat()
    assert [row["source_ref"] for row in snapshot["evidence"]] == ["qualifying"]
    assert result["authorizes_actions"] is False
    with repo.transaction() as tx:
        saved = tx.incident(item.id)
        assert saved is not None and saved.model_dump() == item.model_dump()
    repo.close()


def test_later_completed_snapshot_cannot_overwrite_newer_capture_or_echo_diagnosis() -> None:
    import json

    import httpx
    import pytest
    from incidents_service.intelligence import IntelligenceError, revision
    from incidents_service.providers import ProviderConfig, StructuredProvider

    repo = Repository("sqlite:///:memory:")
    anchor = now() - timedelta(minutes=1)
    item = Incident(
        id="race-case",
        service="catalog-service",
        environment="dev",
        title="Incident",
        signals=[],
        evidence_ids=["qualifying"],
        analysis=Analysis(
            summary="PRIVATE_PRIOR_GUESS", confidence="low", evidence_ids=["qualifying"]
        ),
        plan=Plan(action="escalate", target="catalog-service", reason="Unknown", risk="high"),
        audit=[],
        created_at=anchor,
        detected_event_at=anchor,
    )
    with repo.transaction() as tx:
        tx.add_event(metric("qualifying", anchor, 5))
        tx.save_incident(item)

    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(json.loads(request.content)["messages"][1]["content"])
        assert "PRIVATE_PRIOR_GUESS" not in payload["question"]
        assert payload["temporal_scope"] == "incident_window"
        with repo.transaction() as tx:
            tx.put_state(
                "investigation:" + item.id,
                {
                    "incident_revision": revision(item),
                    "result": {
                        "snapshot": {"captured_at": (now() + timedelta(seconds=1)).isoformat()}
                    },
                },
            )
        return httpx.Response(503)

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            provider = StructuredProvider(
                ProviderConfig(
                    provider="openai", base_url="http://localhost:8000/v1", model="fixture-only"
                ),
                client,
            )
            agent = Intelligence(repo, Settings(dev_mode=True), None, provider)
            with pytest.raises(IntelligenceError, match="newer_investigation_already_saved"):
                await agent.investigate(item.id)

    asyncio.run(exercise())
    repo.close()
