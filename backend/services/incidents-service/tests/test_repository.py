from pathlib import Path

import pytest
from incidents_service.models import Event
from incidents_service.repository import Repository


def test_transaction_rollback_and_durability(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path}/test.db"
    repo = Repository(url)
    event = Event(
        id="one",
        source="prometheus",
        type="metric",
        service="catalog-service",
        payload={"name": "latency", "value": 0.1},
    )
    with pytest.raises(RuntimeError), repo.transaction() as tx:
        tx.add_event(event, normal=True)
        raise RuntimeError("crash")
    with repo.transaction() as tx:
        assert tx.event("one") is None
        tx.add_event(event, normal=True)
        tx.append_audit(None, {"action": "test"})
        tx.emit(event.model_dump(mode="json"))
    repo.close()
    second = Repository(url)
    with second.transaction() as tx:
        record = tx.event("one")
        assert record is not None and record["id"] == "one"
        assert tx.baseline(event.series()) == [0.1]
        assert len(tx.audits()) == 1
        seq, _ = tx.pending()[0]
        tx.delivered(seq)
        assert not tx.pending()
    second.close()


def test_series_isolates_environment_labels_and_units() -> None:
    a = Event(
        id="a",
        source="prometheus",
        type="metric",
        service="catalog-service",
        payload={"name": "latency", "value": 1, "unit": "seconds"},
    )
    b = a.model_copy(deep=True)
    b.environment = "prod"
    assert a.series() != b.series()
    b.environment = a.environment
    b.payload["unit"] = "milliseconds"
    assert a.series() != b.series()
