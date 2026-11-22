"""Safety guardrails for the disposable CI driver, not a Kubernetes substitute."""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

import pytest

SPEC = importlib.util.spec_from_file_location(
    "kind_evidence_gate", Path(__file__).resolve().parents[4] / "scripts/ci/kind_evidence_gate.py"
)
assert SPEC is not None and SPEC.loader is not None
DRIVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DRIVER)


@pytest.fixture
def fixture_driver(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("GITHUB_RUN_ID", "fixture-run")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_JOB", "kubernetes-evidence")
    return DRIVER


def test_driver_rejects_non_ci_even_with_ambient_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("KUBECONFIG", "/do-not-touch/ambient")
    with pytest.raises(RuntimeError, match="disposable GitHub"):
        DRIVER.directory()


def test_kubectl_requires_owned_cluster_and_explicit_context(
    fixture_driver: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    driver = fixture_driver
    call = Mock(return_value="ok")
    monkeypatch.setattr(driver, "run", call)
    monkeypatch.setenv("KUBECONFIG", "/do-not-touch/ambient")
    with pytest.raises(RuntimeError, match="not created"):
        driver.kubectl("get", "pods")
    call.assert_not_called()
    (driver.directory() / "owned").write_text(driver.owner())
    assert driver.kubectl("get", "pods", capture=True) == "ok"
    args = call.call_args.args[0]
    assert args[1:5] == [
        "--kubeconfig",
        str(driver.directory() / "kubeconfig"),
        "--context",
        "kind-aegis-evidence",
    ]
    assert "/do-not-touch/ambient" not in args


def test_create_refuses_preexisting_named_cluster(
    fixture_driver: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    call = Mock(return_value="aegis-evidence\n")
    monkeypatch.setattr(fixture_driver, "run", call)
    with pytest.raises(RuntimeError, match="pre-existing"):
        fixture_driver.create()
    assert call.call_count == 1
    assert not (fixture_driver.directory() / "owned").exists()


def test_cleanup_never_deletes_unowned_cluster(
    fixture_driver: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    call = Mock(return_value="")
    monkeypatch.setattr(fixture_driver, "run", call)
    fixture_driver.cleanup()
    call.assert_not_called()
    marker = fixture_driver.directory() / "owned"
    marker.write_text(fixture_driver.owner())
    fixture_driver.cleanup()
    assert call.call_args.args[0][1:] == ["delete", "cluster", "--name", "aegis-evidence"]
    assert not marker.exists()


def test_tool_checksum_mismatch_never_executes_download(
    fixture_driver: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = io.BytesIO(b"not-the-pinned-binary")
    monkeypatch.setattr(fixture_driver.urllib.request, "urlopen", Mock(return_value=response))
    call = Mock()
    monkeypatch.setattr(fixture_driver, "run", call)
    with pytest.raises(ValueError, match="checksum mismatch"):
        fixture_driver.install()
    call.assert_not_called()
    assert not (fixture_driver.directory() / "bin/kind").exists()


def test_stale_marker_cannot_authorize_cluster_deletion(
    fixture_driver: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    call = Mock(return_value="")
    monkeypatch.setattr(fixture_driver, "run", call)
    (fixture_driver.directory() / "owned").write_text("another-run:1:kubernetes-evidence")
    fixture_driver.cleanup()
    call.assert_not_called()
