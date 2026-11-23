from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from incidents_service.deployment_intelligence import Rollout
from incidents_service.deployment_trends import report, trend
from incidents_service.repository import Repository


def test_daily_utc_cohorts_are_disjoint_with_unknown_gaps() -> None:
    repo = Repository("sqlite:///:memory:")
    clock = datetime(2026, 11, 23, 12, tzinfo=UTC)
    midnight = clock.replace(hour=0)
    with repo.transaction() as tx:
        for key, start, outcome, env in [
            ("previous", midnight - timedelta(microseconds=1), "bad", "dev"),
            ("current", midnight, "healthy", "dev"),
            ("unknown", midnight + timedelta(seconds=1), "insufficient", "dev"),
            ("other", midnight, "bad", "prod"),
            ("future", clock + timedelta(seconds=1), "bad", "dev"),
        ]:
            tx.save_rollout(
                Rollout(
                    id=key,
                    service="catalog-service",
                    environment=env,
                    deployment_id=key,
                    identity_explicit=True,
                    revision=key,
                    previous_revision=None,
                    started_at=start,
                    window_end=start + timedelta(seconds=180),
                    anchor_source="producer_started_at",
                    phase="succeeded",
                    last_phase_at=start,
                    outcome=cast(Literal["bad", "healthy", "insufficient"], outcome),
                ).model_dump(mode="json")
            )
        result = trend(tx, "catalog-service", "dev", clock)
        assert len(result["points"]) == 30
        previous, current = result["points"][-2:]
        assert previous["identified"] == 1 and previous["cfr"] == 1
        assert current["identified"] == 2 and current["cfr"] is None
        assert current["coverage"] == 0.5 and current["unknown"] == 1
        assert result["points"][0]["cfr"] is None
        assert report(tx, "current", "catalog-service", "prod") is None
        assert report(tx, "current", "cart-service", "dev") is None
        review = report(tx, "current", "catalog-service", "dev")
        assert review is not None and review["frozen_risk"] is None
        assert review["actions"] == [] and not review["incident_report_available"]
        assert report(tx, "missing", "catalog-service", "dev") is None
