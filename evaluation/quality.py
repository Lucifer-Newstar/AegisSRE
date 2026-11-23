"""Compute held-out quality metrics from reviewed independent observations.

Does not generate labels or certify that supplied references are truthful.
python -m evaluation.quality INPUT.json OUTPUT.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class Window(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str = Field(min_length=1, max_length=160)
    start: AwareDatetime
    end: AwareDatetime
    truth_anomalous: bool
    predicted_anomalous: bool
    detected_at: AwareDatetime | None = None
    truth_reference: str = Field(min_length=1, max_length=1000)
    prediction_reference: str = Field(min_length=1, max_length=1000)
    service: str = Field(min_length=1, max_length=63)
    metric: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def timing(self) -> Window:
        if self.end <= self.start:
            raise ValueError("Window must have positive duration")
        if self.detected_at and (
            not self.predicted_anomalous or not self.start <= self.detected_at <= self.end
        ):
            raise ValueError("Detection timestamp is inconsistent with window/verdict")
        return self


class Retrieval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    relevant_ids: set[str] = Field(min_length=1)
    retrieved_ids: list[str] = Field(max_length=100)
    truth_reference: str = Field(min_length=1, max_length=1000)
    observation_reference: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def distinct(self) -> Retrieval:
        if len(set(self.retrieved_ids)) != len(self.retrieved_ids):
            raise ValueError("Duplicate retrieved IDs distort recall")
        return self


class DeploymentTrial(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str
    truth_faulty: bool
    predeploy_at: AwareDatetime
    started_at: AwareDatetime
    predicted_probability: float | None = Field(default=None, ge=0, le=1)
    rollout_bad_at: AwareDatetime | None = None
    truth_revision: str
    attributed_revision: str | None = None
    eligible_rollback: bool = False
    recovered_after_rollback: bool | None = None
    safety_violations: int = Field(default=0, ge=0)
    truth_reference: str = Field(min_length=1, max_length=1000)
    observation_reference: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def timing(self) -> DeploymentTrial:
        if self.predeploy_at > self.started_at:
            raise ValueError("Post-deploy scores are not pre-deploy predictions")
        if self.rollout_bad_at and self.rollout_bad_at < self.started_at:
            raise ValueError("Bad-rollout flag cannot precede deployment")
        if self.recovered_after_rollback is not None and not self.eligible_rollback:
            raise ValueError("Rollback result outside eligible cohort")
        return self


class QualityDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    partition: Literal["held_out"]
    frozen_manifest_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    frozen_corpus_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    review_reference: str = Field(min_length=1, max_length=1000)
    windows: list[Window] = Field(max_length=100000)
    retrieval: list[Retrieval] = Field(max_length=100000)
    deployments: list[DeploymentTrial] = Field(max_length=100000)

    @model_validator(mode="after")
    def distinct(self) -> QualityDataset:
        for cohort in (self.windows, self.retrieval, self.deployments):
            ids = [row.id for row in cohort]
            if len(ids) != len(set(ids)):
                raise ValueError("Duplicate observation ID")
        # One metric/service cannot count overlapping windows twice.
        windows = sorted(self.windows, key=lambda row: (row.service, row.metric, row.start))
        for before, after in zip(windows, windows[1:], strict=False):
            if (
                before.service == after.service
                and before.metric == after.metric
                and before.end > after.start
            ):
                raise ValueError("Overlapping detector windows")
        return self


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def summarize(dataset: QualityDataset) -> dict[str, Any]:
    tp = sum(row.truth_anomalous and row.predicted_anomalous for row in dataset.windows)
    fp = sum(not row.truth_anomalous and row.predicted_anomalous for row in dataset.windows)
    fn = sum(row.truth_anomalous and not row.predicted_anomalous for row in dataset.windows)
    tn = sum(not row.truth_anomalous and not row.predicted_anomalous for row in dataset.windows)
    faults = [row for row in dataset.deployments if row.truth_faulty]
    scored = [row for row in faults if row.predicted_probability is not None]
    eligible = [row for row in faults if row.eligible_rollback]
    latencies = [
        (row.detected_at - row.start).total_seconds()
        for row in dataset.windows
        if row.truth_anomalous and row.detected_at
    ]
    return {
        "detection": {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
            "precision": ratio(tp, tp + fp),
            "recall": ratio(tp, tp + fn),
            "f1": ratio(2 * tp, 2 * tp + fp + fn),
            "latency_seconds": latencies,
            "latency_observed": len(latencies),
            "positive_windows": tp + fn,
        },
        "retrieval": {
            "queries": len(dataset.retrieval),
            "mean_recall_at5": sum(
                len(row.relevant_ids.intersection(row.retrieved_ids[:5])) / len(row.relevant_ids)
                for row in dataset.retrieval
            )
            / len(dataset.retrieval)
            if dataset.retrieval
            else None,
        },
        "deployment": {
            "trials": len(dataset.deployments),
            "faulty": len(faults),
            "risk_scored_faulty": len(scored),
            "risk_recall_over_all_faulty": ratio(
                sum(
                    row.predicted_probability is not None and row.predicted_probability >= 0.5
                    for row in faults
                ),
                len(faults),
            ),
            "correlation_accuracy_over_all_faulty": ratio(
                sum(row.attributed_revision == row.truth_revision for row in faults), len(faults)
            ),
            "flag_under180s_over_all_faulty": ratio(
                sum(
                    row.rollout_bad_at is not None
                    and (row.rollout_bad_at - row.started_at).total_seconds() < 180
                    for row in faults
                ),
                len(faults),
            ),
            "eligible_rollbacks": len(eligible),
            "rollback_success_over_eligible": ratio(
                sum(row.recovered_after_rollback is True for row in eligible), len(eligible)
            ),
            "rollback_missing_results": sum(
                row.recovered_after_rollback is None for row in eligible
            ),
            "safety_violations": sum(row.safety_violations for row in dataset.deployments),
        },
        "review_reference": dataset.review_reference,
        "limitations": [
            "References/digests are declarations, not verified by this reporter. No measured dataset is supplied by the code.",
            "Unknown predictions remain in faulty-cohort denominators. No-result is not success.",
            "Detector truth requires independent predeclared windows. Detection latency uses window start, which must be reviewed as actual onset.",
            "This report alone does not establish adequate repetitions, genuine manual baseline, live model quality or project completion.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    raw = args.input.read_bytes()
    if len(raw) > 32_000_000:
        raise ValueError("Dataset exceeds32MB")
    result = summarize(QualityDataset.model_validate_json(raw))
    result["input_sha256"] = hashlib.sha256(raw).hexdigest()
    with args.output.open("x") as output:
        json.dump(result, output, indent=2, allow_nan=False)
        output.write("\n")


if __name__ == "__main__":
    main()
