"""Authored provenance fixtures, not held-out experiments."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from evaluation.capture import canonical
from evaluation.cohort import Bundle, ReviewedSession, build, checked_record, verified_session
from evaluation.timing import TimingJournal


def evidence(root: Path, workflow: str = "manual") -> dict[str, Any]:
    root.mkdir()
    (root / "control").mkdir()
    inputs = {"schedule": [{"pair_id": "http-5xx-01", "fault": "http-5xx",
                            "workflows": ["manual", "aegis"]}], "corpus_files": {"authored": "f" * 64}}
    manifest = {"inputs": inputs, "inputs_sha256": canonical(inputs)}
    (root / "manifest.json").write_text(json.dumps(manifest))
    (root / "environment.json").write_text("{}")
    (root / "controller.log").write_text("Authored unit fixture only")
    (root / "review-required.json").write_text("{}")
    writer = TimingJournal(root / "timing.jsonl")
    writer.record("session_started", pair_id="http-5xx-01", workflow=workflow,
                  operator="Authored operator", inputs_sha256=canonical(inputs))
    writer.record("human_acknowledgement", acknowledgement="detected", operator="Authored operator")
    writer.record("human_acknowledgement", acknowledgement="action-start", operator="Authored operator")
    writer.record("authored_recovery_point")
    rows = [json.loads(line) for line in (root / "timing.jsonl").read_text().splitlines()]
    start, detection, action, recovery = [row["wall_at"] for row in rows]
    writer.record("controller_boundary", control={"stage": "restoration_requested", "recorded_at": recovery})
    writer.record("controller_boundary", control={"stage": "restored_control_state", "recorded_at": recovery})
    writer.record("session_stopped", observer_errors=[])
    final = writer.close()
    (root / "final-digest.txt").write_text(final + "\n")
    (root / "control/run-unit.jsonl").write_text(
        json.dumps({"stage": "restoration_requested", "recorded_at": recovery}) + "\n" +
        json.dumps({"stage": "restored_control_state", "recorded_at": recovery}) + "\n")
    index = {"schema_version": "matched-session-1", "status": "captured_not_reviewed",
        "final_sha256": final, "files": {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}}
    (root / "session-index.json").write_text(json.dumps(index))
    return {"directory": str(root), "retained_final_digest": final,
        "review_reference": "authored-review-not-research",
        "environment_equivalence_reference": "authored-pair-review",
        "onset_evidence_reference": "authored-onset-review",
        "detection_evidence_reference": "authored-detection-review",
        "record": {"id": workflow + "-authored", "pair_id": "http-5xx-01", "fault": "http-5xx",
            "workflow": workflow, "manual_observer": "Authored operator" if workflow == "manual" else None,
            "status": "timeout", "onset_at": start, "deadline_at": recovery,
            "detected_at": detection, "ground_truth_recovered": False,
            "truth_reference": "authored-raw-references", "observation_reference": "authored-observation",
            "environment_digest": "e" * 64, "manifest_digest": canonical(inputs),
            "frozen_corpus_digest": canonical(inputs["corpus_files"])},
        "corrective_action_at": action}


def test_intact_session_and_timeout_cohort(tmp_path: Path) -> None:
    manual = evidence(tmp_path / "manual")
    aegis = evidence(tmp_path / "aegis", "aegis")
    bundle = Bundle.model_validate({"schema_version": "reviewed-cohort-1", "partition": "held_out",
        "comparison_profile": "approved_small_3_per_fault", "reviewer": "Authored reviewer",
        "review_reference": "unit-only", "sessions": [manual, aegis],
        "excluded_attempt_references": ["authored-missed-onset-attempt"]})
    dataset, report = build(bundle)
    assert len(dataset.records) == 2
    assert report["cohort_complete"] is False
    assert report["provenance"]["sessions_verified_against_retained_anchors"] == 2
    assert report["provenance"]["excluded_attempt_references"] == ["authored-missed-onset-attempt"]
    assert all(r.recovered_at is None for r in dataset.records)


@pytest.mark.parametrize("case", ["tamper", "extra", "anchor", "symlink", "truncated"])
def test_invalid_evidence_rejected(tmp_path: Path, case: str) -> None:
    root = tmp_path / "session"
    review = evidence(root)
    digest = review["retained_final_digest"]
    if case == "tamper":
        (root / "environment.json").write_text("changed")
    elif case == "extra":
        (root / "unexpected").write_text("extra")
    elif case == "anchor":
        digest = "f" * 64
    elif case == "symlink":
        (root / "controller.log").unlink()
        (root / "controller.log").symlink_to(root / "environment.json")
    else:
        (root / "timing.jsonl").write_text("")
    with pytest.raises(ValueError):
        verified_session(root, digest)


def test_wrong_manual_ack_and_frozen_identity_rejected(tmp_path: Path) -> None:
    raw = evidence(tmp_path / "session")
    raw["record"]["detected_at"] = raw["record"]["onset_at"]
    with pytest.raises(ValueError, match="first retained acknowledgement"):
        checked_record(ReviewedSession.model_validate(raw))
    raw["record"]["detected_at"] = None
    raw["record"]["manifest_digest"] = "f" * 64
    with pytest.raises(ValueError, match="manifest/corpus"):
        checked_record(ReviewedSession.model_validate(raw))


def test_cleanup_cannot_receive_recovery_credit(tmp_path: Path) -> None:
    raw = evidence(tmp_path / "session")
    raw["record"].update(status="complete", ground_truth_recovered=True,
                          recovered_at=raw["record"]["deadline_at"])
    raw.update(recovery_attribution="manual", recovery_evidence_reference="authored",
               corrective_action_reference="authored")
    with pytest.raises(ValueError, match="at/after cleanup"):
        checked_record(ReviewedSession.model_validate(raw))


def test_recovery_requires_reviewed_action_and_evidence(tmp_path: Path) -> None:
    raw = evidence(tmp_path / "session")
    raw["record"].update(status="complete", ground_truth_recovered=True,
                          recovered_at=raw["record"]["deadline_at"])
    with pytest.raises(ValidationError, match="Credited recovery"):
        ReviewedSession.model_validate(raw)


def test_deadline_after_cleanup_rejected(tmp_path: Path) -> None:
    raw = evidence(tmp_path / "session")
    raw["record"]["deadline_at"] = "2099-01-01T00:00:00+00:00"
    with pytest.raises(ValueError, match="beyond automatic cleanup"):
        checked_record(ReviewedSession.model_validate(raw))


def test_same_session_cannot_fill_two_cohort_slots(tmp_path: Path) -> None:
    raw = evidence(tmp_path / "session")
    bundle = Bundle.model_validate({"schema_version": "reviewed-cohort-1", "partition": "held_out",
        "comparison_profile": "approved_small_3_per_fault", "reviewer": "Unit reviewer",
        "review_reference": "unit-only", "sessions": [raw, raw]})
    with pytest.raises(ValueError, match="reused"):
        build(bundle)
