"""Reset mechanics only, never deletes a real node in unit tests."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts import local_evaluation
from scripts.ci import kind_platform_gate, local_identity


def test_reset_requires_explicit_flag_before_any_access(monkeypatch: pytest.MonkeyPatch) -> None:
    check = Mock()
    monkeypatch.setattr(local_evaluation, "preflight", check)
    with pytest.raises(RuntimeError, match="confirm-owned-reset"):
        local_evaluation.reset_owned(confirmed=False)
    check.assert_not_called()


@pytest.mark.parametrize("blocked", ["unowned", "comparison-active", "chaos-active", "dirty"])
def test_bad_baseline_never_deletes_node(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blocked: str,
) -> None:
    monkeypatch.setenv("AEGIS_LOCAL_EVALUATION", "0")
    monkeypatch.setattr(local_identity, "base", lambda: tmp_path)
    monkeypatch.setattr(local_evaluation, "preflight", lambda: {})
    monkeypatch.setattr(kind_platform_gate, "owned", lambda: blocked != "unowned")
    monkeypatch.setattr(subprocess, "check_output", lambda args, **kw:
                        " M changed" if blocked == "dirty" else "a" * 40)
    if blocked.endswith("active"):
        (tmp_path / blocked).touch()
    delete = Mock()
    monkeypatch.setattr(kind_platform_gate, "cleanup", delete)
    with pytest.raises(RuntimeError):
        local_evaluation.reset_owned(confirmed=True)
    delete.assert_not_called()


def test_reset_archives_before_fresh_baseline_and_never_reuses_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AEGIS_LOCAL_EVALUATION", "0")
    root = tmp_path / "fixture"
    root.mkdir()
    (root / "bin").mkdir()
    for name in ("kind", "kubectl"):
        (root / "bin" / name).write_text("Authored inert executable fixture")
    (tmp_path / "infra/kind").mkdir(parents=True)
    (tmp_path / "infra/kind/ci-versions.json").write_text(json.dumps({
        name + "_sha256": hashlib.sha256((root / "bin" / name).read_bytes()).hexdigest()
        for name in ("kind", "kubectl")}))
    monkeypatch.setattr(local_evaluation, "ROOT", tmp_path)
    monkeypatch.setattr(local_identity, "base", lambda: root)
    original = local_identity.initialize()
    monkeypatch.setattr(local_identity, "node_identity", lambda: "b" * 64)
    monkeypatch.setattr(local_evaluation, "preflight", lambda: {})
    monkeypatch.setattr(subprocess, "check_output", lambda args, **kw:
                        "a" * 40 if "rev-parse" in args else "")
    monkeypatch.setattr(local_evaluation, "docker", lambda *args: "")
    monkeypatch.setattr(kind_platform_gate, "owned", lambda: True)
    monkeypatch.setattr(kind_platform_gate, "diagnostics", Mock())
    cleanup = Mock()
    create = Mock()
    monkeypatch.setattr(kind_platform_gate, "cleanup", cleanup)
    monkeypatch.setattr(kind_platform_gate, "create", create)
    monkeypatch.setattr(kind_platform_gate, "kubectl", Mock())
    from scripts import enable_scoped_executor
    monkeypatch.setattr(enable_scoped_executor, "enable", Mock())
    archive = local_evaluation.reset_owned(confirmed=True)
    cleanup.assert_called_once()
    create.assert_called_once()
    assert archive.is_dir() and archive != root
    assert (archive / "reset-source.json").exists()
    assert (root / "fresh-baseline.json").exists()
    assert (root / "bin/kind").read_bytes() == (archive / "bin/kind").read_bytes()
    assert local_identity.owner() != original
