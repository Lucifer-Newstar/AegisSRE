"""Authored runner mechanics, not manual data or benchmark measurements."""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from evaluation import session
from evaluation.timing import verify


def fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Mock, Path]:
    manifest_path = tmp_path / "manifest.json"
    manifest = {"inputs_sha256": "a" * 64, "inputs": {"source_revision": "b" * 40,
        "schedule": [{"pair_id": "http-5xx-01", "fault": "http-5xx",
                      "workflows": ["manual", "aegis"]}]}}
    manifest_path.write_text(json.dumps(manifest))
    monkeypatch.setattr(session, "validate_manifest", lambda _: manifest)
    forwards = Mock()
    api = SimpleNamespace(NS="owned", FIXTURE={"AEGIS_API_TOKEN": "authored-disposable-test"},
        Forwards=lambda: forwards, kubectl=Mock(return_value='{"items":[]}'),
        directory=lambda: tmp_path, owner=lambda: "authored-owner")
    from chaoslab import __main__ as controller
    monkeypatch.setattr(controller, "driver", lambda: api)
    monkeypatch.setattr(session, "fetch", lambda *a, **kw: {"status": 200})
    monkeypatch.setenv("AEGIS_API_TOKEN", "authored-unit-placeholder")
    from scripts import check_gateway_stack, check_runtime_stack
    request = Mock(side_effect=lambda path, **kw: ([] if path.startswith("/api/v1/incidents")
        else {"executor": "kubernetes", "policy": {"version": "authored"}}))
    monkeypatch.setattr(check_gateway_stack, "request", request)
    monkeypatch.setattr(check_runtime_stack, "wait_for", lambda check, *a: check())
    # No threads, human, real clock, network or cluster are simulated as data.
    monkeypatch.setattr(session, "Thread", lambda **kw: Mock(is_alive=lambda: False))
    monkeypatch.setattr(Event, "wait", lambda *a: False)
    monkeypatch.setattr(time, "sleep", lambda _: None)

    def launch(*args: Any, **kwargs: Any) -> Any:
        path = Path(args[0][-1]) / "run-authored.jsonl"
        path.write_text(json.dumps({"stage": "injection_applied"}) + "\n" +
                        json.dumps({"stage": "restoration_requested"}) + "\n")
        return Mock(poll=lambda: 0, returncode=0)

    monkeypatch.setattr(subprocess, "Popen", launch)
    return api, request, manifest_path


@pytest.mark.parametrize("workflow", ["manual", "aegis"])
def test_workflow_policy_and_cleanup_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, workflow: str,
) -> None:
    api, request, manifest = fixture(tmp_path, monkeypatch)
    output = tmp_path / "session"
    session.run(manifest, output, "http-5xx-01", workflow, "Authored test operator")
    writes = [call for call in request.call_args_list if call.kwargs]
    assert [call.kwargs["body"]["mode"] for call in writes] == [
        "observe" if workflow == "manual" else "auto-safe", "observe"]
    assert all(call.args[0] == "/api/v1/autonomy" for call in writes)
    rows = [json.loads(line) for line in (output / "timing.jsonl").read_text().splitlines()]
    boundaries = [r["data"] for r in rows if r["kind"] == "controller_boundary"]
    assert [r["cleanup_excludes_later_remediation_credit"] for r in boundaries] == [False, True]
    assert not any(r["kind"] == "human_acknowledgement" for r in rows)
    worksheet = json.loads((output / "review-required.json").read_text())
    assert worksheet["recovered_at"] is None and worksheet["detected_at"] is None
    index = json.loads((output / "session-index.json").read_text())
    assert "review-required.json" in index["files"]
    assert verify(output / "timing.jsonl", index["final_sha256"]) == len(rows)
    assert not (tmp_path / "comparison-active").exists()
    api.Forwards().close.assert_called_once()


def test_simulation_rejected_for_aegis_and_lock_retained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    api, request, manifest = fixture(tmp_path, monkeypatch)
    request.side_effect = lambda *a, **kw: {"executor": "simulation", "policy": {}}
    with pytest.raises(RuntimeError, match="actual deployed"):
        session.run(manifest, tmp_path / "session", "http-5xx-01", "aegis", "Operator")
    assert request.call_args_list[-1].kwargs["body"]["mode"] == "observe"
    assert not (tmp_path / "session/session-index.json").exists()
    assert (tmp_path / "comparison-active").exists()
    api.Forwards().close.assert_called_once()


def test_child_failure_keeps_partial_digest_and_returns_observe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, request, manifest = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: Mock(poll=lambda: 1, returncode=1))
    with pytest.raises(RuntimeError, match="controller failed"):
        session.run(manifest, tmp_path / "session", "http-5xx-01", "aegis", "Operator")
    assert (tmp_path / "session/final-digest.txt").exists()
    assert not (tmp_path / "session/session-index.json").exists()
    assert request.call_args_list[-1].kwargs["body"]["mode"] == "observe"


def test_outside_schedule_and_existing_lock_refused_before_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    api, request, manifest = fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="outside frozen"):
        session.run(manifest, tmp_path / "unused", "wrong", "manual", "Operator")
    (tmp_path / "comparison-active").write_text("other")
    with pytest.raises(FileExistsError):
        session.run(manifest, tmp_path / "unused", "http-5xx-01", "manual", "Operator")
    request.assert_not_called()
    api.kubectl.assert_not_called()
    assert not (tmp_path / "unused").exists()


def test_unowned_fixture_cannot_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, request, manifest = fixture(tmp_path, monkeypatch)
    from chaoslab import __main__ as controller
    monkeypatch.setattr(controller, "driver", Mock(side_effect=RuntimeError("unowned")))
    with pytest.raises(RuntimeError, match="unowned"):
        session.run(manifest, tmp_path / "unused", "http-5xx-01", "manual", "Operator")
    request.assert_not_called()
    assert not (tmp_path / "unused").exists()


def test_active_incident_blocks_aegis_and_safety_stop_still_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, request, manifest = fixture(tmp_path, monkeypatch)
    request.side_effect = lambda path, **kw: ([{"status": "investigating"}]
        if path.startswith("/api/v1/incidents")
        else {"executor": "kubernetes", "policy": {}})
    with pytest.raises(RuntimeError, match="carryover"):
        session.run(manifest, tmp_path / "session", "http-5xx-01", "aegis", "Operator")
    writes = [call.kwargs["body"]["mode"] for call in request.call_args_list if call.kwargs]
    assert writes == ["observe"]
    assert (tmp_path / "comparison-active").exists()


def test_safety_stop_failure_still_closes_and_retains_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    api, request, manifest = fixture(tmp_path, monkeypatch)

    def reply(path: str, **kwargs: Any) -> Any:
        if kwargs.get("body", {}).get("actor") == "evaluation-safety-stop":
            raise OSError("authored failed mode write")
        return [] if path.startswith("/api/v1/incidents") else {"executor": "kubernetes", "policy": {}}

    request.side_effect = reply
    with pytest.raises(OSError, match="failed mode"):
        session.run(manifest, tmp_path / "session", "http-5xx-01", "manual", "Operator")
    api.Forwards().close.assert_called_once()
    assert (tmp_path / "session/final-digest.txt").exists()
    assert not (tmp_path / "session/session-index.json").exists()
    assert (tmp_path / "comparison-active").exists()
