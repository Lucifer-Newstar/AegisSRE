"""Capture mechanics tests. Fixtures are authored inputs, not measured trials."""
from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any

import pytest

from evaluation import capture
from evaluation.report import FAULTS


def setup_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    root = tmp_path / "source"
    (root / "infra/k8s").mkdir(parents=True)
    (root / "infra/k8s/workload.yaml").write_text("replicas: 1\n")
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "runbook.md").write_text("Authored test corpus, not held-out truth.\n")
    monkeypatch.setattr(capture, "ROOT", root)
    monkeypatch.setattr(capture, "source_clean", lambda: True)
    monkeypatch.setattr(capture, "revision", lambda: "a" * 40)
    return tmp_path / "manifest.json", corpus


def test_freeze_and_verify(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest, corpus = setup_inputs(tmp_path, monkeypatch)
    capture.freeze(manifest, corpus)
    result = capture.validate_manifest(manifest)
    assert len(result["inputs"]["schedule"]) == 100
    assert {row["fault"] for row in result["inputs"]["schedule"]} == FAULTS
    with pytest.raises(FileExistsError):
        capture.freeze(manifest, corpus)
    (corpus / "runbook.md").write_text("Changed corpus")
    with pytest.raises(ValueError, match="corpus changed"):
        capture.validate_manifest(manifest)


def test_tampered_manifest_and_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest, corpus = setup_inputs(tmp_path, monkeypatch)
    capture.freeze(manifest, corpus)
    monkeypatch.setattr(capture, "source_clean", lambda: False)
    with pytest.raises(ValueError, match="Source changed"):
        capture.validate_manifest(manifest)
    monkeypatch.setattr(capture, "source_clean", lambda: True)
    data = json.loads(manifest.read_text())
    data["inputs"]["source_revision"] = "b" * 40
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="digest/schema"):
        capture.validate_manifest(manifest)


def test_symlinks_and_empty_corpus_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="1..1000"):
        capture.tree_files(tmp_path)
    (tmp_path / "link").symlink_to("/etc/passwd")
    with pytest.raises(ValueError, match="symlinks"):
        capture.tree_files(tmp_path)


def test_fixed_destinations() -> None:
    for port, path in [(80, "/"), (9001, "https://example.org"), (8201, "//example.org")]:
        with pytest.raises(ValueError):
            capture.fetch(port, path)


def test_capture_keeps_truth_separate_without_metrics_claims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, corpus = setup_inputs(tmp_path, monkeypatch)
    capture.freeze(manifest, corpus)
    closed: list[bool] = []

    class Forwards:
        def start(self, *args: Any) -> None:
            pass

        def close(self) -> None:
            closed.append(True)

    api = SimpleNamespace(NS="test-owned", Forwards=Forwards,
                          kubectl=lambda *a, **kw: '{"items": []}')
    monkeypatch.setattr(capture, "driver", lambda: api)
    monkeypatch.setattr(capture, "fetch", lambda *a, **kw: {"status": 200, "body": []})
    monkeypatch.setattr(time, "sleep", lambda _: None)
    monkeypatch.setattr(Event, "wait", lambda self, timeout=None: True)

    def run(fault: str, seconds: int, output: Path) -> Path:
        output.mkdir()
        path = output / "authored-truth.jsonl"
        path.write_text('{"stage":"authored-test-only"}\n')
        return path

    monkeypatch.setattr(capture, "run", run)
    output = tmp_path / "trial"
    capture.trial(manifest, output, "http-5xx", 1, 1)
    index = json.loads((output / "capture.json").read_text())
    assert index["status"] == "captured_not_reviewed" and closed
    assert "control/authored-truth.jsonl" in index["files"]
    assert "records" not in index and "mttd_seconds" not in index
    rows = [json.loads(line) for line in (output / "observations.jsonl").read_text().splitlines()]
    assert not any("authored-test-only" in json.dumps(row) for row in rows)
    with pytest.raises(FileExistsError):
        capture.trial(manifest, output, "http-5xx", 1, 1)


def test_unowned_cluster_refuses_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest, corpus = setup_inputs(tmp_path, monkeypatch)
    capture.freeze(manifest, corpus)

    def unowned() -> Any:
        raise RuntimeError("unowned")

    monkeypatch.setattr(capture, "driver", unowned)
    output = tmp_path / "trial"
    with pytest.raises(RuntimeError, match="unowned"):
        capture.trial(manifest, output, "http-5xx", 1, 1)
    assert not output.exists()
