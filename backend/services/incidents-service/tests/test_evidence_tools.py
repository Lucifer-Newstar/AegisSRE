from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from incidents_service.evidence_tools import (
    CitedAnswer,
    Hypothesis,
    ReadOnlyTools,
    clean_text,
    evidence_only,
    minimize,
)
from incidents_service.knowledge import KnowledgeDocument, KnowledgeStore
from incidents_service.models import Event, now
from incidents_service.repository import Repository


def event(identity: str = "observation", **overrides: Any) -> Event:
    return Event.model_validate(
        {
            "id": identity,
            "service": "catalog-service",
            "source": "registry",
            "type": "health",
            "payload": {"status": "unknown"},
            **overrides,
        }
    )


def tools(repo: Repository, store: KnowledgeStore | None = None) -> ReadOnlyTools:
    return ReadOnlyTools(repo, store, allowed_targets=["catalog-service"], environment="dev")


def test_scope_missing_and_no_write_tools() -> None:
    repo = Repository("sqlite:///:memory:")
    with repo.transaction() as tx:
        tx.add_event(event(service="cart-service"))
        tx.add_event(event("production", environment="prod"))
    snapshot = tools(repo).collect("catalog-service", "Is it healthy?")
    assert not snapshot.evidence
    assert len(snapshot.tool_calls) == 7
    assert all(call.status in {"missing", "unavailable"} for call in snapshot.tool_calls)
    assert snapshot.authorizes_actions is False
    assert "unknown" in evidence_only(snapshot).summary
    with pytest.raises(ValueError, match="allowed service"):
        tools(repo).collect("other-service", "restart")
    repo.close()


def test_fresh_stale_future_and_opaque_citations() -> None:
    repo = Repository("sqlite:///:memory:")
    clock = now()
    with repo.transaction() as tx:
        tx.add_event(event("old", timestamp=clock - timedelta(minutes=10)))
        tx.add_event(
            event(
                "future",
                type="log",
                source="loki",
                timestamp=clock + timedelta(seconds=10),
                payload={"message": "Future evidence", "level": "ERROR"},
            )
        )
        tx.add_event(
            event(
                "current",
                type="trace",
                source="tempo",
                timestamp=clock,
                payload={"duration_ms": 500},
            )
        )
    snapshot = tools(repo).collect("catalog-service", "latency?", at=clock)
    calls = {call.name: call for call in snapshot.tool_calls}
    assert calls["get_health"].status == calls["get_logs"].status == "stale"
    assert calls["get_traces"].status == "available"
    assert all(item.id.startswith("event:") for item in snapshot.evidence)
    assert "source_ref" not in json.dumps(snapshot.provider_payload("question"))
    assert evidence_only(snapshot).evidence_ids
    repo.close()


def test_redaction_and_bounded_provider_payload() -> None:
    assert "hunter2" not in clean_text("password=hunter2")
    assert "abc.def" not in clean_text("Bearer abc.def")
    assert "user:pass" not in clean_text("https://user:pass@site.invalid/private?value=secret")
    assert minimize({"API_KEY": "private", "safe": "ok"}) == {"API_KEY": "[REDACTED]", "safe": "ok"}
    repo = Repository("sqlite:///:memory:")
    with repo.transaction() as tx:
        for index in range(2):
            for kind in ("health", "trace", "k8s_event"):
                tx.add_event(
                    event(
                        f"{kind}-{index}",
                        type=kind,
                        payload={f"key{x}": "測" * 3000 for x in range(1)},
                    )
                )
    snapshot = tools(repo).collect("catalog-service", "status?")
    payload = snapshot.provider_payload("測" * 2000)
    assert len(json.dumps(payload, ensure_ascii=False).encode()) < 24000
    assert all(
        len(json.dumps(item.content, ensure_ascii=False).encode()) < 1000
        for item in snapshot.evidence
    )
    repo.close()


def test_knowledge_citations_are_versioned_and_not_observations() -> None:
    repo = Repository("sqlite:///:memory:")
    store = KnowledgeStore(repo)
    document = KnowledgeDocument(
        id="guide",
        title="Database",
        kind="runbook",
        source="test:guide",
        content="Database connection refused and timeout",
    )
    store.upsert(document)
    snapshot = tools(repo, store).collect("catalog-service", "database timeout")
    assert snapshot.evidence and snapshot.evidence[0].kind == "knowledge"
    assert snapshot.evidence[0].content["checksum"]
    assert "unknown" in evidence_only(snapshot).summary
    answer = CitedAnswer(
        summary="A hypothesis",
        evidence_ids=[snapshot.evidence[0].id],
        hypotheses=[
            Hypothesis(
                cause="database_outage",
                confidence="low",
                explanation="Guide suggests a check",
                evidence_ids=[snapshot.evidence[0].id],
            )
        ],
        limitations=["Not verified"],
    )
    with pytest.raises(ValueError, match="current_observation"):
        answer.validate_citations(snapshot)
    previous = snapshot.evidence[0].id
    store.upsert(document.model_copy(update={"content": "Database timeout changed"}))
    assert (
        tools(repo, store).collect("catalog-service", "database timeout").evidence[0].id != previous
    )
    repo.close()


def test_unknown_and_empty_citations_rejected() -> None:
    repo = Repository("sqlite:///:memory:")
    with repo.transaction() as tx:
        tx.add_event(event())
    snapshot = tools(repo).collect("catalog-service", "health?")
    for ids, message in ((["invented"], "unknown_citation"), ([], "uncited_answer")):
        answer = CitedAnswer(
            summary="Readout", evidence_ids=ids, hypotheses=[], limitations=["Not verified"]
        )
        with pytest.raises(ValueError, match=message):
            answer.validate_citations(snapshot)
    answer = evidence_only(snapshot)
    answer.validate_citations(snapshot)
    repo.close()
