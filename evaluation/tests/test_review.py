"""Authored capture fixtures, not measured evaluation results."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from evaluation.review import packet, verified_capture


def fixture(root: Path) -> dict[str, object]:
    (root / "control").mkdir()
    for name in ["environment.json", "manifest.json", "control/truth.jsonl"]:
        (root / name).write_text("{}\n")
    (root / "observations.jsonl").write_text('\n'.join(json.dumps({"stage": "sample", "domain": {"status": status}})
                                                        for status in [200, 503, None, 200]))
    index: dict[str, object] = {"schema_version": "capture-1", "status": "captured_not_reviewed",
        "fault": "http-5xx", "workflow": "aegis", "pair_id": "http-5xx-01",
        "files": {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in root.rglob("*") if p.is_file()}}
    (root / "capture.json").write_text(json.dumps(index))
    return index


def test_packet_never_infers_outcomes(tmp_path: Path) -> None:
    fixture(tmp_path)
    result = packet(tmp_path)
    assert result["raw_domain_sample_counts"] == {"200": 2, "503": 1, "connection_or_read_error": 1}
    assert result["status"] == "human_review_required"
    assert all(v is None for v in result["review"].values())
    assert "records" not in result


def test_tampered_or_extra_files_rejected(tmp_path: Path) -> None:
    fixture(tmp_path)
    (tmp_path / "manifest.json").write_text("changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        verified_capture(tmp_path)


def test_unindexed_file_rejected(tmp_path: Path) -> None:
    fixture(tmp_path)
    (tmp_path / "unindexed.json").write_text("{}")
    with pytest.raises(ValueError, match="Unexpected files"):
        verified_capture(tmp_path)


def test_escape_and_symlink_rejected(tmp_path: Path) -> None:
    index = fixture(tmp_path)
    index["files"] = {"../outside": "a" * 64, "environment.json": "a" * 64,
                      "manifest.json": "a" * 64, "observations.jsonl": "a" * 64,
                      "control/truth.jsonl": "a" * 64}
    (tmp_path / "capture.json").write_text(json.dumps(index))
    with pytest.raises(ValueError, match="Unsafe inventory"):
        verified_capture(tmp_path)


def test_index_symlink_rejected(tmp_path: Path) -> None:
    fixture(tmp_path)
    (tmp_path / "copy.json").write_bytes((tmp_path / "capture.json").read_bytes())
    (tmp_path / "capture.json").unlink()
    (tmp_path / "capture.json").symlink_to(tmp_path / "copy.json")
    with pytest.raises(ValueError, match="Invalid capture index"):
        verified_capture(tmp_path)
