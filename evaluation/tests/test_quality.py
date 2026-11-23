from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from evaluation.quality import QualityDataset, summarize


def dataset() -> dict[str, Any]:
    start = datetime(2026, 11, 22, tzinfo=UTC)
    return {
        "partition": "held_out",
        "frozen_manifest_digest": "a" * 64,
        "frozen_corpus_digest": "b" * 64,
        "review_reference": "unit-fixture-not-research",
        "windows": [
            {
                "id": str(index),
                "start": (start + timedelta(minutes=index)).isoformat(),
                "end": (start + timedelta(minutes=index + 1)).isoformat(),
                "truth_anomalous": truth,
                "predicted_anomalous": predicted,
                "truth_reference": "unit-truth",
                "prediction_reference": "unit-prediction",
                "service": "catalog-service",
                "metric": "latency",
            }
            for index, (truth, predicted) in enumerate(
                [(True, True), (False, True), (True, False), (False, False)]
            )
        ],
        "retrieval": [
            {
                "id": "query",
                "relevant_ids": ["a", "b"],
                "retrieved_ids": ["a", "c"],
                "truth_reference": "unit",
                "observation_reference": "unit",
            }
        ],
        "deployments": [
            {
                "id": "faulty",
                "truth_faulty": True,
                "predeploy_at": start.isoformat(),
                "started_at": start.isoformat(),
                "truth_revision": "bad-v1",
                "eligible_rollback": True,
                "truth_reference": "unit",
                "observation_reference": "unit",
            }
        ],
    }


def test_confusion_matrix_unknown_risk_denominator_and_retrieval() -> None:
    result = summarize(QualityDataset.model_validate(dataset()))
    assert (
        result["detection"]["precision"]
        == result["detection"]["recall"]
        == result["detection"]["f1"]
        == 0.5
    )
    assert result["detection"]["latency_observed"] == 0
    assert result["retrieval"]["mean_recall_at5"] == 0.5
    assert result["deployment"]["risk_recall_over_all_faulty"] == 0
    assert result["deployment"]["rollback_success_over_eligible"] == 0
    assert result["deployment"]["rollback_missing_results"] == 1


def test_empty_data_is_not_perfect_accuracy() -> None:
    body = dataset()
    body.update(windows=[], retrieval=[], deployments=[])
    result = summarize(QualityDataset.model_validate(body))
    assert result["detection"]["f1"] is None
    assert result["retrieval"]["mean_recall_at5"] is None
    assert result["deployment"]["risk_recall_over_all_faulty"] is None


@pytest.mark.parametrize(
    "case", ["overlap", "duplicate", "late-score", "early-flag", "duplicate-retrieval"]
)
def test_invalid_experiments_are_rejected(case: str) -> None:
    body = dataset()
    if case == "overlap":
        body["windows"][1]["start"] = body["windows"][0]["start"]
    elif case == "duplicate":
        body["windows"][1]["id"] = body["windows"][0]["id"]
    elif case == "late-score":
        body["deployments"][0]["predeploy_at"] = "2026-11-22T00:00:01Z"
    elif case == "early-flag":
        body["deployments"][0]["rollout_bad_at"] = "2026-11-21T23:59:59Z"
    else:
        body["retrieval"][0]["retrieved_ids"] = ["a", "a"]
    with pytest.raises(ValidationError):
        QualityDataset.model_validate(body)
