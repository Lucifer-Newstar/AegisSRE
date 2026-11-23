"""Verify retained matched sessions and report explicitly reviewed outcomes.

python -m evaluation.cohort REVIEW_BUNDLE.json OUTPUT_DIRECTORY
This never labels symptoms, invents a human or certifies a reviewer's judgment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from evaluation.capture import canonical
from evaluation.report import Dataset, Run, summarize
from evaluation.timing import verify

MAX_FILE = 32_000_000
MAX_TOTAL = 256_000_000


def date(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("Evidence timestamps require timezone offsets")
    return result


def verified_session(root: Path, retained_digest: str) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, str]]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Expected real session directory")
    index_path = root / "session-index.json"
    if index_path.is_symlink() or index_path.stat().st_size > 1_000_000:
        raise ValueError("Invalid session index")
    index = json.loads(index_path.read_text())
    if index.get("schema_version") != "matched-session-1" or index.get("status") != "captured_not_reviewed":
        raise ValueError("Not a completed raw session; retain partial attempts separately")
    files = index.get("files", {})
    required = {"environment.json", "manifest.json", "timing.jsonl", "final-digest.txt", "controller.log", "review-required.json"}
    if not isinstance(files, dict) or not required <= files.keys() or not len(files) <= 100:
        raise ValueError("Missing or excessive session inventory")
    if not any(name.startswith("control/run-") for name in files):
        raise ValueError("Missing actual controller journal")
    total = 0
    for name, expected in files.items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != name:
            raise ValueError("Unsafe session inventory path")
        path = root / relative
        if any(part.is_symlink() for part in [path, *path.parents]):
            raise ValueError("Symlink in session evidence")
        if not path.is_file() or path.stat().st_size > MAX_FILE:
            raise ValueError("Missing or oversized session evidence")
        total += path.stat().st_size
        if total > MAX_TOTAL:
            raise ValueError("Session evidence exceeds total bound")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("Session hash mismatch: " + name)
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if actual != set(files) | {"session-index.json"}:
        raise ValueError("Unexpected files in immutable session")
    if index["final_sha256"] != retained_digest or (root / "final-digest.txt").read_text().strip() != retained_digest:
        raise ValueError("Session differs from separately retained digest")
    verify(root / "timing.jsonl", retained_digest)
    rows = [json.loads(line) for line in (root / "timing.jsonl").read_text().splitlines()]
    manifest = json.loads((root / "manifest.json").read_text())
    if canonical(manifest["inputs"]) != manifest["inputs_sha256"]:
        raise ValueError("Frozen manifest digest mismatch")
    return manifest, rows, files


class ReviewedSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    directory: str
    retained_final_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    review_reference: str = Field(min_length=1, max_length=1000)
    environment_equivalence_reference: str = Field(min_length=1, max_length=1000)
    onset_evidence_reference: str = Field(min_length=1, max_length=1000)
    detection_evidence_reference: str | None = Field(default=None, min_length=1, max_length=1000)
    recovery_evidence_reference: str | None = Field(default=None, min_length=1, max_length=1000)
    corrective_action_reference: str | None = Field(default=None, min_length=1, max_length=1000)
    corrective_action_at: AwareDatetime | None = None
    recovery_attribution: Literal["manual", "aegis", "none"] = "none"
    record: Run

    @model_validator(mode="after")
    def review_fields(self) -> ReviewedSession:
        if self.record.detected_at and not self.detection_evidence_reference:
            raise ValueError("Detection requires reviewed evidence")
        if self.record.recovered_at and (not self.recovery_evidence_reference
                or not self.corrective_action_reference or not self.corrective_action_at
                or self.recovery_attribution != self.record.workflow):
            raise ValueError("Credited recovery requires actual workflow action and independent evidence")
        if self.corrective_action_at and self.record.recovered_at and not (
            self.record.onset_at <= self.corrective_action_at <= self.record.recovered_at
        ):
            raise ValueError("Corrective action outside onset/recovery interval")
        return self


def checked_record(review: ReviewedSession) -> Run:
    root = Path(review.directory)
    manifest, rows, files = verified_session(root, review.retained_final_digest)
    starts = [r for r in rows if r["kind"] == "session_started"]
    if len(starts) != 1 or rows[-1]["kind"] != "session_stopped" or rows[-1]["data"]["observer_errors"]:
        raise ValueError("Session lifecycle/observation incomplete")
    start = starts[0]
    identity = start["data"]
    record = review.record
    pairs = [r for r in manifest["inputs"]["schedule"] if r["pair_id"] == record.pair_id]
    if (identity["pair_id"] != record.pair_id or identity["workflow"] != record.workflow
            or len(pairs) != 1 or pairs[0]["fault"] != record.fault):
        raise ValueError("Reviewed record does not match frozen session identity")
    if identity["operator"].startswith("ci-"):
        raise ValueError("CI smoke cannot be a held-out workflow measurement")
    if identity.get("inputs_sha256") != manifest["inputs_sha256"]:
        raise ValueError("Session start differs from frozen manifest anchor")
    if record.workflow == "manual" and record.manual_observer != identity["operator"]:
        raise ValueError("Actual attributed human required; CI smoke is not a manual baseline")
    if record.manifest_digest != manifest["inputs_sha256"] or record.frozen_corpus_digest != canonical(manifest["inputs"]["corpus_files"]):
        raise ValueError("Reviewed manifest/corpus identity differs from retained source")
    began, ended = date(start["wall_at"]), date(rows[-1]["wall_at"])
    controller_rows = [json.loads(line) for name in files if name.startswith("control/run-")
                       for line in (root / name).read_text().splitlines() if line]
    ingested = [r["data"]["control"] for r in rows if r["kind"] == "controller_boundary"]
    if controller_rows != ingested:
        raise ValueError("Timing journal does not retain every controller boundary")
    cleanup = [date(r["recorded_at"]) for r in controller_rows
               if r["stage"] in {"load_completed", "restoration_requested"}]
    if not cleanup:
        raise ValueError("Missing controller censoring boundary")
    if len([r for r in controller_rows if r["stage"] == "restored_control_state"]) != 1:
        raise ValueError("Completed session requires retained control restoration")
    # Review may set an earlier boundary, e.g. hook expiry or spontaneous recovery.
    if not began <= record.onset_at < record.deadline_at <= min(ended, *cleanup):
        raise ValueError("Reviewed interval extends outside observation or beyond automatic cleanup")
    if record.recovered_at and record.recovered_at >= min(cleanup):
        raise ValueError("Recovery at/after cleanup cannot receive workflow credit")
    if record.workflow == "manual" and record.detected_at:
        acknowledgements = [date(r["wall_at"]) for r in rows if r["kind"] == "human_acknowledgement"
            and r["data"]["acknowledgement"] == "detected" and date(r["wall_at"]) >= record.onset_at]
        if not acknowledgements or record.detected_at != min(acknowledgements):
            raise ValueError("Manual detection must be the first retained acknowledgement after onset")
    if record.workflow == "manual" and record.recovered_at:
        action_starts = [date(r["wall_at"]) for r in rows if r["kind"] == "human_acknowledgement"
            and r["data"]["acknowledgement"] == "action-start"]
        if review.corrective_action_at not in action_starts:
            raise ValueError("Manual corrective action must match retained action-start acknowledgement")
    return record


class Bundle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["reviewed-cohort-1"]
    partition: Literal["held_out"]
    comparison_profile: Literal["approved_small_3_per_fault", "original_10_per_fault"]
    reviewer: str = Field(min_length=1, max_length=100)
    review_reference: str = Field(min_length=1, max_length=1000)
    sessions: list[ReviewedSession] = Field(max_length=1000)
    excluded_attempt_references: list[str] = Field(default_factory=list, max_length=1000)


def build(bundle: Bundle) -> tuple[Dataset, dict[str, Any]]:
    directories = [str(Path(session.directory).resolve()) for session in bundle.sessions]
    anchors = [session.retained_final_digest for session in bundle.sessions]
    if len(set(directories)) != len(directories) or len(set(anchors)) != len(anchors):
        raise ValueError("Session evidence reused in cohort")
    records = [checked_record(session) for session in bundle.sessions]
    dataset = Dataset(partition="held_out", comparison_profile=bundle.comparison_profile,
                      records=records, review_reference=bundle.review_reference)
    report = summarize(dataset)
    report["provenance"] = {
        "reviewer": bundle.reviewer,
        "sessions_verified_against_retained_anchors": len(records),
        "excluded_attempt_references": bundle.excluded_attempt_references,
        "manual_detection_semantics": "operator acknowledgement latency",
        "environment_equivalence_is_reviewed_not_inferred": True,
        "reviewer_judgments_not_independently_certified": True,
        "one_operator_non_blinded_small_sample_learning_order_effects": True,
    }
    return dataset, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_bundle", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    raw = args.review_bundle.read_bytes()
    if len(raw) > MAX_FILE:
        raise ValueError("Review bundle exceeds32MB")
    bundle = Bundle.model_validate_json(raw)
    dataset, report = build(bundle)
    report["review_bundle_sha256"] = hashlib.sha256(raw).hexdigest()
    if any(args.output.resolve().is_relative_to(Path(session.directory).resolve())
           for session in bundle.sessions):
        raise ValueError("Keep report output outside immutable sessions")
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "validated-dataset.json").write_text(dataset.model_dump_json(indent=2) + "\n")
    (args.output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
