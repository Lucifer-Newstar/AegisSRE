"""Verify captured bytes and prepare an explicitly unreviewed outcome worksheet.

python -m evaluation.review CAPTURE_DIRECTORY OUTPUT.json
No outcome timestamp or correctness judgment is filled automatically.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

MAX_FILE_BYTES = 32_000_000
MAX_TOTAL_BYTES = 128_000_000


def verified_capture(root: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Capture must be a real directory")
    index_path = root / "capture.json"
    if index_path.is_symlink() or index_path.stat().st_size > 1_000_000:
        raise ValueError("Invalid capture index")
    index: dict[str, Any] = json.loads(index_path.read_text())
    if index.get("schema_version") != "capture-1" or index.get("status") != "captured_not_reviewed":
        raise ValueError("Not a completed unreviewed capture")
    files = index.get("files", {})
    if not isinstance(files, dict) or not 4 <= len(files) <= 100:
        raise ValueError("Invalid capture inventory")
    required = {"environment.json", "manifest.json", "observations.jsonl"}
    if not required <= set(files) or not any(k.startswith("control/") for k in files):
        raise ValueError("Missing required capture evidence")
    result: dict[str, bytes] = {}
    total = 0
    for name, expected in files.items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != name:
            raise ValueError("Unsafe inventory path")
        path = root / relative
        if any(parent.is_symlink() for parent in [path, *path.parents] if parent != root.parent):
            raise ValueError("Symlink in capture inventory")
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("Missing or oversized capture file")
        total += path.stat().st_size
        if total > MAX_TOTAL_BYTES:
            raise ValueError("Capture exceeds total bound")
        raw = path.read_bytes()
        if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
            raise ValueError("Invalid SHA256")
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("Capture hash mismatch: " + name)
        result[name] = raw
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if actual != set(files) | {"capture.json"}:
        raise ValueError("Unexpected files in immutable capture")
    return index, result


def packet(root: Path) -> dict[str, Any]:
    index, files = verified_capture(root)
    rows = [json.loads(line) for line in files["observations.jsonl"].splitlines() if line]
    counts: dict[str, int] = {}
    for row in rows:
        if row.get("stage") == "sample":
            status = row.get("domain", {}).get("status")
            key = "connection_or_read_error" if status is None else str(status)
            counts[key] = counts.get(key, 0) + 1
    return {
        "schema_version": "review-packet-1", "status": "human_review_required",
        "capture_index_sha256": hashlib.sha256((root / "capture.json").read_bytes()).hexdigest(),
        "source_capture": str(root.resolve()), "verified_files": index["files"],
        "fault_label_from_control": index["fault"], "workflow": index["workflow"],
        "pair_id": index["pair_id"], "raw_domain_sample_counts": counts,
        "review": {"reviewer": None, "review_reference": None,
            "independent_symptom_onset_at": None, "onset_evidence_reference": None,
            "first_qualifying_detection_at": None, "detection_evidence_reference": None,
            "independent_recovery_at": None, "recovery_evidence_reference": None,
            "recovery_attribution": None, "censoring_or_timeout_reason": None,
            "top1_cause_correct": None, "cause_evidence_reference": None,
            "eligible_action": None, "executed_action": None,
            "autonomous_success": None, "safety_violations": None,
            "environment_pairing_verified": None, "held_out_partition_verified": None},
        "limitations": [
            "Hash verification checks consistency with this index, not independent authenticity.",
            "Raw status counts are not detector confusion windows or outcome classifications.",
            "Control application/restoration times are not independent symptom/recovery times.",
            "Aegis must not receive credit for control-runner restoration.",
            "No manual trial, outcome, correctness judgment or report-schema record generated.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = packet(args.capture)
    # Review output must not modify the verified immutable capture directory.
    if args.output.resolve().is_relative_to(args.capture.resolve()):
        raise ValueError("Keep review output outside the immutable capture")
    with args.output.open("x") as output:
        json.dump(result, output, indent=2, allow_nan=False)
        output.write("\n")


if __name__ == "__main__":
    main()
