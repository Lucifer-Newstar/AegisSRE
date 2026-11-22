"""Validated held-out experiment reporting; never creates missing observations.

python -m evaluation.report INPUT.json OUTPUT.json
Inputs are independently collected/reviewed records, not runner control times.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

FAULTS = {"cpu-saturation", "memory-exhaustion", "container-crash", "database-outage",
          "network-latency", "http-5xx", "dependency-failure", "config-error",
          "faulty-deployment", "traffic-spike"}


class Run(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str = Field(min_length=1, max_length=160)
    pair_id: str = Field(min_length=1, max_length=160)
    fault: str
    workflow: Literal["manual", "aegis"]
    status: Literal["complete", "timeout", "failed"]
    onset_at: AwareDatetime
    deadline_at: AwareDatetime
    detected_at: AwareDatetime | None = None
    recovered_at: AwareDatetime | None = None
    ground_truth_recovered: bool
    predicted_recovered: bool | None = None
    top1_cause: str | None = None
    autonomous_eligible: bool = False
    autonomous_executed: bool = False
    autonomous_succeeded: bool | None = None
    safety_violations: int = Field(default=0, ge=0)
    truth_reference: str = Field(min_length=1, max_length=1000)
    observation_reference: str = Field(min_length=1, max_length=1000)
    manual_observer: str | None = Field(default=None, max_length=100)
    environment_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    manifest_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    frozen_corpus_digest: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def consistent(self) -> Run:
        if self.fault not in FAULTS or self.deadline_at <= self.onset_at:
            raise ValueError("Unknown fault or nonpositive observation window")
        for at in (self.detected_at, self.recovered_at):
            if at and not self.onset_at <= at <= self.deadline_at:
                raise ValueError("Observation outside declared interval")
        if self.recovered_at and not self.ground_truth_recovered:
            raise ValueError("Recovery timestamp contradicts independent truth")
        if self.status == "complete" and (not self.ground_truth_recovered or not self.recovered_at):
            raise ValueError("Complete requires independently observed recovery")
        if self.workflow == "manual" and not self.manual_observer:
            raise ValueError("Manual measurements require an attributed observer")
        if self.autonomous_executed and (not self.autonomous_eligible or self.workflow != "aegis"):
            raise ValueError("Autonomous execution outside eligible Aegis cohort")
        if self.autonomous_succeeded is not None and not self.autonomous_executed:
            raise ValueError("Autonomy result without execution")
        return self


class Dataset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1"] = "1"
    partition: Literal["held_out"]
    records: list[Run] = Field(max_length=100000)
    review_reference: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def distinct(self) -> Dataset:
        ids = [r.id for r in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate run ID")
        pairs: dict[str, list[Run]] = {}
        for r in self.records:
            pairs.setdefault(r.pair_id, []).append(r)
        for rows in pairs.values():
            if len({r.workflow for r in rows}) != len(rows):
                raise ValueError("Duplicate workflow in a paired experiment")
            if len({(r.fault, r.environment_digest, r.manifest_digest,
                     r.frozen_corpus_digest) for r in rows}) != 1:
                raise ValueError("Paired runs differ in fault/environment/manifest/corpus")
        return self


def describe(values: list[float]) -> dict[str, float | int | None]:
    return {"n": len(values), "mean": statistics.mean(values) if values else None,
            "sample_std": statistics.stdev(values) if len(values) >= 2 else None}


def seconds(end: datetime | None, start: datetime) -> float | None:
    return (end - start).total_seconds() if end else None


def summarize(dataset: Dataset) -> dict[str, Any]:
    groups: list[dict[str, object]] = []
    adequate = True
    for fault in sorted(FAULTS):
        for workflow in ("manual", "aegis"):
            rows = [r for r in dataset.records if r.fault == fault and r.workflow == workflow]
            counts = {state: sum(r.status == state for r in rows)
                      for state in ("complete", "timeout", "failed")}
            adequate = adequate and len(rows) >= 10 and counts["complete"] >= 10
            detection = [v for r in rows if (v := seconds(r.detected_at, r.onset_at)) is not None]
            recovery = [v for r in rows if (v := seconds(r.recovered_at, r.onset_at)) is not None]
            judged = [r for r in rows if r.predicted_recovered is not None]
            cited = [r for r in rows if r.top1_cause is not None]
            eligible = [r for r in rows if r.autonomous_eligible]
            executed = [r for r in rows if r.autonomous_executed]
            groups.append({"fault": fault, "workflow": workflow, "attempted": len(rows),
                "counts": counts, "mttd_seconds": describe(detection), "mttr_seconds": describe(recovery),
                "detection_missing": len(rows)-len(detection), "recovery_censored": len(rows)-len(recovery),
                "top1_accuracy": sum(r.top1_cause == fault for r in cited)/len(cited) if cited else None,
                "top1_coverage": len(cited)/len(rows) if rows else None,
                "verification_accuracy": sum(r.predicted_recovered == r.ground_truth_recovered for r in judged)/len(judged) if judged else None,
                "verification_coverage": len(judged)/len(rows) if rows else None,
                "unrecovered_closed": sum(r.predicted_recovered is True and not r.ground_truth_recovered for r in rows),
                "eligible_actions": len(eligible), "executed_actions": len(executed),
                "autonomy_success_over_eligible": sum(r.autonomous_succeeded is True for r in eligible)/len(eligible) if eligible else None,
                "autonomy_unobserved_results": sum(r.autonomous_succeeded is None for r in executed),
                "safety_violations": sum(r.safety_violations for r in rows)})
    paired = []
    unpaired_ids = []
    for pair in sorted({r.pair_id for r in dataset.records}):
        workflows = {r.workflow: r for r in dataset.records if r.pair_id == pair}
        if set(workflows) != {"manual", "aegis"}:
            unpaired_ids.append(pair)
            continue
        for metric, field in (("mttd", "detected_at"), ("mttr", "recovered_at")):
            manual, aegis = workflows["manual"], workflows["aegis"]
            m, a = seconds(getattr(manual, field), manual.onset_at), seconds(getattr(aegis, field), aegis.onset_at)
            paired.append({"pair_id": pair, "fault": manual.fault, "metric": metric,
                           "manual_minus_aegis_seconds": m-a if m is not None and a is not None else None})
    return {"schema_version": "1", "cohort_complete": adequate and not unpaired_ids,
            "unpaired_experiment_ids": unpaired_ids,
            "record_count": len(dataset.records), "groups": groups, "paired_differences": paired,
            "review_reference": dataset.review_reference,
            "limitations": ["Input references/digests are declarations, not verified by this offline reporter.",
                "Means/std use observed intervals only; missing/censored outcomes remain in counts and coverage.",
                "Repetition counts alone do not prove detector precision/recall, causal correctness, RAG recall, DI accuracy or model quality.",
                "Manual inputs must be observed by the named human, never inferred from an assumed response delay.",
                "cohort_complete checks pairing and ten completed runs per fault/workflow only, not all project acceptance thresholds."]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    raw = args.input.read_bytes()
    if len(raw) > 32_000_000:
        raise ValueError("Dataset exceeds32MB")
    dataset = Dataset.model_validate_json(raw)
    result = summarize(dataset)
    result["input_sha256"] = hashlib.sha256(raw).hexdigest()
    # Never overwrite a prior result silently.
    with args.output.open("x") as output:
        json.dump(result, output, indent=2, allow_nan=False)
        output.write("\n")


if __name__ == "__main__":
    main()
