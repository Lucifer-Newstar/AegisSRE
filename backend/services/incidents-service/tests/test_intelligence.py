from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from incidents_service.config import Settings
from incidents_service.evidence_tools import ReadOnlyTools
from incidents_service.intelligence import AskRequest, Intelligence, IntelligenceError
from incidents_service.main import create_app
from incidents_service.models import Analysis, Event, Incident, Plan
from incidents_service.providers import ProviderConfig, StructuredProvider
from incidents_service.repository import Repository


def seed(repo: Repository) -> Incident:
    item = Incident(
        id="incident_test",
        service="catalog-service",
        environment="dev",
        title="Incident",
        signals=[],
        evidence_ids=["metric"],
        analysis=Analysis(summary="Elevated latency", confidence="low", evidence_ids=["metric"]),
        plan=Plan(action="escalate", target="catalog-service", reason="Unknown cause", risk="high"),
        audit=[],
    )
    with repo.transaction() as tx:
        tx.add_event(
            Event(
                id="metric",
                service="catalog-service",
                source="prometheus",
                type="metric",
                payload={"name": "latency_seconds", "value": 0.9},
            )
        )
        tx.save_incident(item)
    return item


def output(citation: str) -> dict[str, Any]:
    return {
        "summary": "Persisted latency is elevated; cause remains unverified.",
        "evidence_ids": [citation],
        "hypotheses": [
            {
                "cause": "unknown",
                "confidence": "low",
                "explanation": "More evidence is needed",
                "evidence_ids": [citation],
            }
        ],
        "limitations": ["Not proof of cause or overall health"],
    }


def test_disabled_ask_is_explicit_and_does_not_reserve_inference() -> None:
    repo = Repository("sqlite:///:memory:")
    seed(repo)
    agent = Intelligence(repo, Settings(dev_mode=True), None)
    result = asyncio.run(
        agent.ask(AskRequest(service="catalog-service", question="How is latency?"))
    )
    assert result.inference_status == "disabled"
    assert result.engine == "evidence-only-v1"
    assert result.snapshot.tool_calls[0].name == "get_metrics"
    with repo.transaction() as tx:
        assert tx.get_state("inference:quota") is None
    asyncio.run(agent.close())
    repo.close()


def test_model_calls_are_detached_and_quota_is_durable(tmp_path: Any) -> None:
    database = "sqlite:///" + str(tmp_path / "quota.db")
    repo = Repository(database)
    seed(repo)
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1

        # A separate thread can acquire the transaction while inference runs.
        def check() -> None:
            with repo.transaction() as tx:
                assert tx.get_state("inference:quota")["daily"] == 1

        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(check).result(timeout=2)
        body = json.loads(request.content)
        payload = json.loads(body["messages"][1]["content"])
        assert "tools" not in body
        assert payload["evidence"][0]["id"].startswith("event:")
        answer = output(payload["evidence"][0]["id"])
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}]
            },
        )

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            provider = StructuredProvider(
                ProviderConfig(
                    provider="openai", base_url="http://localhost:8000/v1", model="fixture-only"
                ),
                client,
            )
            agent = Intelligence(
                repo, Settings(dev_mode=True, llm_requests_per_day=1), None, provider
            )
            result = await agent.ask(AskRequest(service="catalog-service", question="latency?"))
            assert result.inference_status == "complete"
            assert result.answer.hypotheses[0].cause == "unknown"
            with pytest.raises(IntelligenceError, match="quota_exhausted"):
                await agent.ask(AskRequest(service="catalog-service", question="again?"))

    asyncio.run(exercise())
    assert calls == 1
    repo.close()
    reopened = Repository(database)
    agent = Intelligence(reopened, Settings(dev_mode=True, llm_requests_per_day=1), None)
    with pytest.raises(IntelligenceError, match="quota_exhausted"):
        agent.reserve()
    reopened.close()


@pytest.mark.parametrize("mode", ["transport_failure", "invented_citation", "uncited"])
def test_provider_failures_are_visible_and_not_retried(mode: str) -> None:
    repo = Repository("sqlite:///:memory:")
    seed(repo)
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if mode == "transport_failure":
            raise httpx.ConnectError("private response must not leak", request=request)
        answer = output("fabricated")
        if mode == "uncited":
            answer["evidence_ids"] = []
            answer["hypotheses"] = []
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}]
            },
        )

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            provider = StructuredProvider(
                ProviderConfig(
                    provider="openai", base_url="http://localhost:8000/v1", model="fixture-only"
                ),
                client,
            )
            agent = Intelligence(repo, Settings(dev_mode=True), None, provider)
            result = await agent.ask(AskRequest(service="catalog-service", question="latency?"))
            assert result.inference_status == "failed"
            assert result.engine == "evidence-only-v1"
            assert result.diagnostic in {"provider_request_failed", "invalid_answer_citations"}
            assert "private response" not in result.model_dump_json()
            with repo.transaction() as tx:
                assert tx.get_state("inference:quota")["daily"] == 1

    asyncio.run(exercise())
    assert calls == 1
    repo.close()


def test_sidecar_does_not_change_plans_and_marks_later_revisions() -> None:
    repo = Repository("sqlite:///:memory:")
    original = seed(repo)
    agent = Intelligence(repo, Settings(dev_mode=True), None)
    result = asyncio.run(agent.investigate(original.id))
    assert result["authorizes_actions"] is False
    with repo.transaction() as tx:
        current = tx.incident(original.id)
        assert current is not None
        assert current.model_dump() == original.model_dump()
        current.approval = "rejected"
        tx.save_incident(current)
    assert agent.investigation(original.id)["matches_incident_revision"] is False
    repo.close()


def test_revision_race_discards_result() -> None:
    repo = Repository("sqlite:///:memory:")
    original = seed(repo)

    def respond(request: httpx.Request) -> httpx.Response:
        with repo.transaction() as tx:
            current = tx.incident(original.id)
            assert current is not None
            current.status = "escalated"
            tx.save_incident(current)
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
            with pytest.raises(IntelligenceError, match="incident_changed"):
                await agent.investigate(original.id)

    asyncio.run(exercise())
    with repo.transaction() as tx:
        assert tx.get_state("investigation:" + original.id) is None
    repo.close()


def test_api_auth_scope_and_no_write_tool_exposure() -> None:
    repo = Repository("sqlite:///:memory:")
    item = seed(repo)
    app = create_app(Settings(api_token="test-token"), repo)
    with TestClient(app) as client:
        assert (
            client.post(
                "/ask", json={"service": "catalog-service", "question": "health?"}
            ).status_code
            == 401
        )
        client.headers["Authorization"] = "Bearer test-token"
        assert client.get("/intelligence/status").json()["write_tools"] == []
        assert client.get("/intelligence/tools", params={"service": "other"}).status_code == 422
        assert (
            client.post("/ask", json={"service": "other", "question": "health?"}).status_code == 422
        )
        response = client.post(
            "/ask", json={"service": "catalog-service", "question": "restart all nodes"}
        )
        assert response.status_code == 200
        assert response.json()["inference_status"] == "disabled"
        assert response.json()["snapshot"]["authorizes_actions"] is False
        assert client.get(f"/incidents/{item.id}/investigation").status_code == 404
        assert client.post(f"/incidents/{item.id}/investigate").status_code == 200
        assert client.get(f"/incidents/{item.id}/investigation").status_code == 200
        assert (
            client.post(
                "/ask",
                json={"service": "catalog-service", "question": "health?", "tool": "execute"},
            ).status_code
            == 422
        )
        assert client.post("/incidents/missing/investigate").status_code == 404
    assert (
        len(
            ReadOnlyTools(repo, None, allowed_targets=["catalog-service"], environment="dev")
            .collect("catalog-service", "health")
            .tool_calls
        )
        == 7
    )
    repo.close()
