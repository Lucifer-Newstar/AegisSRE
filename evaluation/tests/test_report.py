from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from evaluation.report import Dataset, Run, describe, summarize


def row(**changes: Any) -> Run:
    at = datetime(2026, 1, 1, tzinfo=UTC)
    value = dict(id="example-aegis", pair_id="example-pair", fault="http-5xx", workflow="aegis",
        status="complete", onset_at=at, deadline_at=at+timedelta(seconds=120),
        detected_at=at+timedelta(seconds=10), recovered_at=at+timedelta(seconds=30),
        ground_truth_recovered=True, predicted_recovered=True, top1_cause="http-5xx",
        truth_reference="authored-unit-fixture", observation_reference="authored-unit-fixture",
        environment_digest="a"*64, manifest_digest="b"*64, frozen_corpus_digest="c"*64)
    return Run.model_validate({**value, **changes})


def test_missing_observations_are_not_zero_or_silently_dropped() -> None:
    good = row()
    timeout = row(id="timeout", pair_id="timeout", status="timeout", detected_at=None,
                  recovered_at=None, ground_truth_recovered=False, predicted_recovered=True)
    result = summarize(Dataset(partition="held_out", records=[good, timeout],
                               review_reference="unit-only"))
    group = next(g for g in result["groups"] if g["fault"] == "http-5xx" and g["workflow"] == "aegis")
    assert group["attempted"] == 2
    assert group["mttd_seconds"] == {"n": 1, "mean": 10, "sample_std": None}
    assert group["recovery_censored"] == 1 and group["unrecovered_closed"] == 1
    assert result["cohort_complete"] is False


def test_paired_difference_uses_each_run_onset_not_wall_clock_difference() -> None:
    platform = row()
    manual = row(id="manual", workflow="manual", manual_observer="unit-fixture-human",
                 detected_at=platform.onset_at+timedelta(seconds=20))
    result = summarize(Dataset(partition="held_out", records=[platform, manual], review_reference="unit"))
    assert result["paired_differences"][0]["manual_minus_aegis_seconds"] == 10


@pytest.mark.parametrize("changes", [
    {"workflow": "manual"}, {"onset_at": "2026-01-01T00:00:00"},
    {"ground_truth_recovered": False}, {"fault": "unknown"},
    {"autonomous_executed": True}, {"autonomous_succeeded": True},
    {"detected_at": "2025-12-31T23:59:59Z"},
])
def test_invalid_truth_or_authority_record_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        row(**changes)


def test_pair_mismatch_and_duplicates_rejected() -> None:
    for records in ([row(), row()], [row(), row(id="manual", workflow="manual",
        manual_observer="unit", manifest_digest="d"*64)]):
        with pytest.raises(ValidationError):
            Dataset(partition="held_out", records=records, review_reference="unit")


def test_sample_standard_deviation_and_no_data() -> None:
    assert describe([]) == {"n": 0, "mean": None, "sample_std": None}
    assert describe([1, 3]) == {"n": 2, "mean": 2, "sample_std": pytest.approx(2**0.5)}
