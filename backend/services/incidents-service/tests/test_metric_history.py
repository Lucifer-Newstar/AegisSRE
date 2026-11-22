from datetime import timedelta

from fastapi.testclient import TestClient
from incidents_service.config import Settings
from incidents_service.main import create_app
from incidents_service.metric_history import history
from incidents_service.models import Event, now
from incidents_service.repository import Repository


def test_history_scope_gaps_units_and_real_sources() -> None:
    repo = Repository("sqlite:///:memory:")
    point = now()
    with repo.transaction() as tx:
        for index, (value, source, service, environment, labels, unit) in enumerate([
            (1, "prometheus", "catalog-service", "dev", {}, "seconds"),
            (3, "prometheus", "catalog-service", "dev", {}, "seconds"),
            (99, "chaoslab", "catalog-service", "dev", {}, "seconds"),
            (99, "prometheus", "payment-service", "dev", {}, "seconds"),
            (99, "prometheus", "catalog-service", "prod", {}, "seconds"),
            (99, "prometheus", "catalog-service", "dev", {"revision":"canary"}, "seconds"),
        ]):
            tx.add_event(Event(id=f"history-{index}", timestamp=point-timedelta(seconds=20),
                type="metric", source=source, service=service, environment=environment,
                payload={"name":"latency_p95","value":value,"labels":labels,"unit":unit}))
        result=history(tx,"catalog-service","dev","latency_p95",point,1,12)
        assert result["status"]=="observed" and result["missing_buckets"]==11
        assert len(result["points"])==1
        sample=result["points"][0]
        assert sample["mean"]==2 and sample["min"]==1 and sample["max"]==3
        assert sample["samples"]==2 and sample["evidence_id"] in {"history-0","history-1"}
        assert result["unit"]=="seconds" and result["truncated"] is False
        empty=history(tx,"cart-service","dev","latency_p95",point,24,288)
        assert empty["status"]=="no_data" and empty["points"]==[]
        tx.add_event(Event(id="mixed-units",timestamp=point-timedelta(seconds=10),
            type="metric",source="prometheus",service="catalog-service",
            payload={"name":"latency_p95","value":1000,"unit":"ms"}))
        mixed=history(tx,"catalog-service","dev","latency_p95",point,1,12)
        assert mixed["status"]=="incompatible_units" and mixed["points"]==[]


def test_history_api_auth_and_bounded_queries() -> None:
    with TestClient(create_app(Settings(api_token="test-token"),Repository("sqlite:///:memory:"))) as http:
        path="/metric-history?service=catalog-service&metric=error_rate"
        assert http.get(path).status_code==401
        http.headers["Authorization"]="Bearer test-token"
        assert http.get(path).json()["status"]=="no_data"
        for suffix in ("&hours=25","&hours=0","&buckets=601","&buckets=1"):
            assert http.get(path+suffix).status_code==422
        assert http.get("/metric-history?service=evil&metric=error_rate").status_code==422
        assert http.get("/metric-history?service=catalog-service&metric=arbitrary").status_code==422
