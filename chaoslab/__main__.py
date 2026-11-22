"""CLI runner restricted to the current newly owned full-platform CI fixture.

No arbitrary Kubernetes object names, namespace, context, URL or commands are
accepted. Ground truth is written separately from the observed platform data.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import signal
import time
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import uuid4

from chaoslab.journal import Journal

ROOT = Path(__file__).resolve().parents[1]
HOOKS = {"http-5xx", "network-latency", "cpu-saturation", "memory-pressure"}
DATABASES = {"database-outage": "shop-postgres", "dependency-failure": "shop-redis"}
FAULTS = HOOKS | set(DATABASES)
WRITE_CONTROL = (
    "import os,sys;from pathlib import Path;"
    "p=Path('/tmp/aegisshop-fault.json');"
    "t=Path('/tmp/aegisshop-fault.json.new');"
    "f=t.open('x');f.write(sys.stdin.read(1025));f.flush();os.fsync(f.fileno());"
    "f.close();os.replace(t,p)"
)
REMOVE_CONTROL = (
    "from pathlib import Path;Path('/tmp/aegisshop-fault.json').unlink(missing_ok=True)"
)


def driver() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "chaos_owned_driver", ROOT / "scripts/ci/kind_platform_gate.py"
    )
    assert spec is not None and spec.loader is not None
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    if not result.owned():
        raise RuntimeError("Chaos requires the current run's newly owned CI cluster")
    return result


def snapshot(api: ModuleType, kind: str, name: str) -> dict[str, Any]:
    value = json.loads(api.kubectl("get", kind, name, "--namespace", api.NS, "-o", "json", capture=True))
    if value.get("metadata", {}).get("namespace") != api.NS:
        raise RuntimeError("Wrong object namespace")
    if value.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/part-of") != "aegisshop":
        raise RuntimeError("Refusing a non-shop workload")
    if not value["metadata"].get("uid"):
        raise RuntimeError("Workload identity unavailable")
    return dict(value)


def _run(api: ModuleType, fault: str, seconds: int, output: Path) -> Path:
    target = DATABASES.get(fault, "catalog-service")
    kind = "statefulset" if fault in DATABASES else "deployment"
    original = snapshot(api, kind, target)
    if original["spec"].get("replicas", 1) != 1:
        raise RuntimeError("The disposable experiment requires exactly one replica")
    env = original["spec"]["template"]["spec"]["containers"][0].get("env", [])
    if fault in HOOKS and not any(
        item.get("name") == "AEGIS_SHOP_FAULTS_ENABLED" and item.get("value") == "true"
        for item in env
    ):
        raise RuntimeError("Fault hooks are not explicitly enabled on the owned fixture")
    journal = Journal(output, "run-" + uuid4().hex)
    attempted = False
    try:
        journal.record("prepared", fault=fault, target=target, requested_seconds=seconds,
                       owner=api.owner(), uid=original["metadata"]["uid"],
                       effect=("application-boundary-delay" if fault == "network-latency"
                               else "bounded-memory-pressure-not-oom" if fault == "memory-pressure"
                               else fault), labels_are_ground_truth_only=True)
        attempted = True  # Any uncertain write still requires restoration.
        journal.record("injection_requested", fault=fault)
        if fault in DATABASES:
            api.kubectl("scale", kind + "/" + target, "--replicas=0", "--namespace", api.NS)
            api.kubectl("wait", "--for=delete", "pod/" + target + "-0", "--namespace", api.NS,
                        "--timeout=90s", timeout=100)
        else:
            magnitude = {"http-5xx": 100, "network-latency": 1000,
                         "cpu-saturation": 500, "memory-pressure": 32}[fault]
            control = json.dumps({"kind": fault, "until": time.time() + seconds + 15,
                                  "magnitude": magnitude})
            api.kubectl("exec", "deployment/" + target, "--namespace", api.NS, "-i", "--",
                        "python", "-c", WRITE_CONTROL, body=control)
        journal.record("injection_applied", fault=fault,
                       onset_semantics="control applied; not independently observed symptom onset")
        time.sleep(seconds)
    except BaseException as error:
        journal.record("run_failed", error_type=type(error).__name__)
        raise
    finally:
        try:
            if attempted:
                current = snapshot(api, kind, target)
                if current["metadata"]["uid"] != original["metadata"]["uid"]:
                    raise RuntimeError("Workload identity changed; automatic restoration refused")
                journal.record("restoration_requested")
                if fault in DATABASES:
                    api.kubectl("scale", kind + "/" + target, "--replicas=1", "--namespace", api.NS)
                    api.kubectl("rollout", "status", kind + "/" + target,
                                "--namespace", api.NS, "--timeout=180s", timeout=200)
                else:
                    api.kubectl("exec", "deployment/" + target, "--namespace", api.NS, "--",
                                "python", "-c", REMOVE_CONTROL)
                journal.record("restored_control_state", independently_verified_health=False,
                               completed_at=datetime.now(UTC).isoformat())
        except BaseException as error:
            journal.record("restoration_failed", error_type=type(error).__name__)
            raise
        finally:
            journal.close()
    return journal.path


def run(fault: str, seconds: int, output: Path) -> Path:
    if fault not in FAULTS or not 1 <= seconds <= 120:
        raise ValueError("Unsupported fault or duration outside 1..120 seconds")
    api = driver()
    lock = api.directory() / "chaos-active"
    # A stale lock deliberately requires investigation, never silent takeover.
    with lock.open("x") as marker:
        marker.write(api.owner())
    result = _run(api, fault, seconds, output)
    lock.unlink()
    return result


def main() -> None:
    def interrupted(signum: int, frame: Any) -> None:
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fault", choices=sorted(FAULTS))
    parser.add_argument("--seconds", type=int, default=15)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(run(args.fault, args.seconds, args.output))


if __name__ == "__main__":
    main()
