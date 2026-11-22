"""Runner unit safety checks, never substitutes for actual cluster fault proof."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from chaoslab import __main__ as runner
from chaoslab.journal import Journal


def fixture_driver() -> Any:
    from types import SimpleNamespace

    api = SimpleNamespace()
    api.NS = "aegissre-demo"
    obj = {"metadata": {"namespace": "aegissre-demo", "uid": "fixture-uid",
                        "labels": {"app.kubernetes.io/part-of": "aegisshop"}},
           "spec": {"replicas": 1, "template": {"spec": {"containers": [{"env": [
               {"name": "AEGIS_SHOP_FAULTS_ENABLED", "value": "true"}
           ]}]}}}}
    api.kubectl = Mock(return_value=json.dumps(obj))
    api.owner = Mock(return_value="run:attempt:job")
    return api


def test_journal_never_overwrites_ground_truth(tmp_path: Path) -> None:
    first = Journal(tmp_path, "fixture")
    first.record("prepared", simulation=False)
    first.close()
    with pytest.raises(FileExistsError):
        Journal(tmp_path, "fixture")
    with pytest.raises(ValueError):
        Journal(tmp_path, "../../escape")
    assert json.loads((tmp_path / "fixture.jsonl").read_text())["simulation"] is False


def test_restore_runs_after_interruption_and_never_claims_health(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = fixture_driver()
    monkeypatch.setattr(runner, "driver", lambda: api)
    api.directory = lambda: tmp_path
    monkeypatch.setattr(time, "sleep", Mock(side_effect=KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        runner.run("database-outage", 1, tmp_path)
    calls = api.kubectl.call_args_list
    assert any("--replicas=0" in call.args for call in calls)
    assert any("--replicas=1" in call.args for call in calls)
    rows = [json.loads(line) for line in next(tmp_path.glob("*.jsonl")).read_text().splitlines()]
    assert any(row["stage"] == "run_failed" for row in rows)
    assert rows[-1]["stage"] == "restored_control_state"
    assert rows[-1]["independently_verified_health"] is False


def test_runner_refuses_changed_identity_before_restore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = fixture_driver()
    normal = api.kubectl.return_value
    changed = json.loads(normal)
    changed["metadata"]["uid"] = "replacement"
    api.kubectl.side_effect = [normal, "", "", json.dumps(changed)]
    monkeypatch.setattr(runner, "driver", lambda: api)
    api.directory = lambda: tmp_path
    monkeypatch.setattr(time, "sleep", Mock())
    with pytest.raises(RuntimeError, match="identity changed"):
        runner.run("database-outage", 1, tmp_path)
    assert not any("--replicas=1" in call.args for call in api.kubectl.call_args_list)
    rows = [json.loads(line) for line in next(tmp_path.glob("*.jsonl")).read_text().splitlines()]
    assert rows[-1]["stage"] == "restoration_failed"


def test_bad_fault_or_duration_never_loads_driver(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    load = Mock()
    monkeypatch.setattr(runner, "driver", load)
    for fault, seconds in [("delete-all", 1), ("database-outage", 0), ("database-outage", 121)]:
        with pytest.raises(ValueError):
            runner.run(fault, seconds, tmp_path)
    load.assert_not_called()


def test_fixed_container_crash_tolerates_only_expected_killed_exec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    api=fixture_driver()
    original=api.kubectl.return_value
    api.kubectl.side_effect=[original, subprocess.CalledProcessError(137,["kubectl"]), original, ""]
    api.directory=lambda:tmp_path
    monkeypatch.setattr(runner,"driver",lambda:api)
    monkeypatch.setattr(time,"sleep",Mock())
    runner.run("container-crash",1,tmp_path)
    calls=api.kubectl.call_args_list
    assert any("import os,signal;os.kill(1,signal.SIGUSR1)" in call.args for call in calls)
    assert any("rollout" in call.args and "status" in call.args for call in calls)
    assert not (tmp_path/"chaos-active").exists()


def test_opt_in_lifespan_really_terminates_its_own_process() -> None:
    import os
    import subprocess
    import sys

    # A fresh child, never the pytest process. No server/port or fake os.kill.
    program = '''
import asyncio, os, signal
from fastapi import FastAPI
from aegisshop_faults import configure_fault_hooks
app = FastAPI()
configure_fault_hooks(app)
async def check():
    async with app.router.lifespan_context(app):
        os.kill(os.getpid(), signal.SIGUSR1)
asyncio.run(check())
'''
    result = subprocess.run([sys.executable, "-c", program],
        env={**os.environ, "AEGIS_SHOP_FAULTS_ENABLED": "true"}, timeout=10)
    assert result.returncode == -9
