from fastapi.testclient import TestClient
from incidents_service.config import Settings
from incidents_service.main import create_app
from incidents_service.models import Analysis, Incident, Plan


def test_authenticated_read_only_knowledge_api_and_disabled_state() -> None:
    config = Settings(
        dev_mode=True,
        knowledge_enabled=True,
        database_url="sqlite:///:memory:",
        api_token="test-token",
    )
    application = create_app(config)
    with TestClient(application) as client:
        assert client.get("/runbooks").status_code == 401
        client.headers["Authorization"] = "Bearer test-token"
        assert len(client.get("/runbooks").json()) == 10
        assert "Safe response" in client.get("/runbooks/cpu-saturation").json()["content"]
        assert client.get("/runbooks/missing").status_code == 404
        response = client.post(
            "/knowledge/search",
            json={"query": "database timeout", "service": "catalog-service", "kind": "runbook"},
        )
        assert response.status_code == 200
        assert response.json()["results"][0]["retrieval_backend"] == "sqlite_exact_cosine"
        assert (
            client.post(
                "/knowledge/search",
                json={"query": "database timeout", "service": "outside-service"},
            ).status_code
            == 422
        )
        assert client.post("/runbooks", json={"command": "no write endpoint"}).status_code == 405
        assert client.get("/knowledge/status").json()["documents"] == 20
        fixture_incident = Incident(
            id="context-fixture",
            service="catalog-service",
            environment="dev",
            title="Memory investigation",
            status="investigating",
            signals=[],
            evidence_ids=["context-evidence"],
            analysis=Analysis(
                summary="Memory exhaustion OOMKilled",
                confidence="low",
                evidence_ids=["context-evidence"],
            ),
            plan=Plan(action="escalate", target="catalog-service", reason="Fixture", risk="high"),
            audit=[],
        )
        with application.state.loop.repo.transaction() as tx:
            tx.save_incident(fixture_incident)
        context = client.get("/incidents/context-fixture/context")
        assert context.status_code == 200
        assert context.json()["knowledge"]
        assert context.json()["read_only"] is True
        assert context.json()["authorizes_actions"] is False
    with TestClient(
        create_app(Settings(dev_mode=True, database_url="sqlite:///:memory:"))
    ) as client:
        assert client.get("/knowledge/status").json() == {"enabled": False}
        assert client.get("/runbooks").status_code == 503

