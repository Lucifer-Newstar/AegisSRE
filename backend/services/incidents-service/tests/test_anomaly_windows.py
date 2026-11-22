from __future__ import annotations

from datetime import timedelta

from incidents_service.anomaly_windows import windows
from incidents_service.config import Settings
from incidents_service.engine import ReliabilityLoop
from incidents_service.models import Event, now
from incidents_service.repository import Repository


def test_only_committed_detector_flags_are_marked_not_incident_intervals() -> None:
    loop = ReliabilityLoop(Repository("sqlite:///:memory:"), Settings(dev_mode=True))
    for index in range(13):
        result = loop.ingest(
            Event(
                id=("x" * 158 + str(index)) if index < 10 else ("x" * 158 + str(index)),
                source="prometheus",
                type="metric",
                service="catalog-service",
                timestamp=now() - timedelta(seconds=20 - index),
                payload={
                    "name": "latency_p95",
                    "value": 10 if index == 12 else 0.1,
                    "unit": "seconds",
                },
            )
        )
    assert result["anomalous"]
    with loop.repo.transaction() as tx:
        actual = windows(tx, "catalog-service", "dev", "latency_p95", now())
        assert len(actual["points"]) == 1
        assert actual["points"][0]["event_id"] == "x" * 158 + "12"
        assert actual["points"][0]["observed"] == 10
        assert windows(tx, "cart-service", "dev", "latency_p95", now())["points"] == []
        assert windows(tx, "catalog-service", "prod", "latency_p95", now())["points"] == []
        assert windows(tx, "catalog-service", "dev", "error_rate", now())["points"] == []
