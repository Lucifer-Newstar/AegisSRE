#!/usr/bin/env python3
"""Own an isolated runner-local kind fixture, never an ambient kube context."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
NAME = "aegis-evidence"
NAMESPACE = "aegissre-demo"
IMAGE = "aegissre/evidence:ci"


def directory() -> Path:
    if os.environ.get("GITHUB_ACTIONS") != "true" or not os.environ.get("RUNNER_TEMP"):
        raise RuntimeError("Only the disposable GitHub runner fixture may run this driver")
    result = Path(os.environ["RUNNER_TEMP"]) / "aegis-kind-evidence"
    result.mkdir(parents=True, exist_ok=True)
    return result


def owner() -> str:
    return ":".join(
        os.environ[key] for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB")
    )


def owned() -> bool:
    marker = directory() / "owned"
    return marker.is_file() and marker.read_text() == owner()


def run(args: list[str], *, timeout: int = 180, capture: bool = False) -> str:
    result = subprocess.run(args, check=True, text=True, capture_output=capture, timeout=timeout)
    return result.stdout if capture else ""


def kubectl(*args: str, timeout: int = 180, capture: bool = False) -> str:
    base = directory()
    if not owned():
        raise RuntimeError("Refusing to use a cluster not created by this fixture")
    return run(
        [
            str(base / "bin/kubectl"),
            "--kubeconfig",
            str(base / "kubeconfig"),
            "--context",
            "kind-" + NAME,
            *args,
        ],
        timeout=timeout,
        capture=capture,
    )


def install() -> None:
    base = directory()
    pins = json.loads((ROOT / "infra/kind/ci-versions.json").read_text())
    for tool in ("kind", "kubectl"):
        url, digest = str(pins[tool + "_url"]), str(pins[tool + "_sha256"])
        expected_prefix = (
            "https://github.com/kubernetes-sigs/kind/releases/download/"
            if tool == "kind"
            else "https://dl.k8s.io/release/"
        )
        if not url.startswith(expected_prefix) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Invalid pinned tool URL/digest")
        destination = base / "bin" / tool
        destination.parent.mkdir(exist_ok=True)
        data = bytearray()
        with urllib.request.urlopen(url, timeout=60) as response:
            while chunk := response.read(65536):
                data.extend(chunk)
                if len(data) > 120_000_000:
                    raise ValueError("Tool download exceeds bound")
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("Pinned tool checksum mismatch")
        destination.write_bytes(data)
        destination.chmod(0o755)
    run([str(base / "bin/kind"), "version"])
    run([str(base / "bin/kubectl"), "version", "--client"])


def create() -> None:
    base = directory()
    binary = str(base / "bin/kind")
    if NAME in run([binary, "get", "clusters"], capture=True).splitlines():
        raise RuntimeError("Refusing to reuse/delete a pre-existing named cluster")
    pins = json.loads((ROOT / "infra/kind/ci-versions.json").read_text())
    image = str(pins["node_image"])
    if not re.fullmatch(r"kindest/node:v[0-9.]+@sha256:[0-9a-f]{64}", image):
        raise ValueError("Node image must be digest pinned")
    run(
        [
            binary,
            "create",
            "cluster",
            "--name",
            NAME,
            "--image",
            image,
            "--kubeconfig",
            str(base / "kubeconfig"),
            "--wait",
            "180s",
        ],
        timeout=300,
    )
    (base / "owned").write_text(owner())
    run([binary, "load", "docker-image", IMAGE, "--name", NAME], timeout=180)
    kubectl("apply", "-f", str(ROOT / "infra/kind/evidence-namespace.yaml"))
    for name in ("serviceaccount", "role", "rolebinding"):
        kubectl("apply", "-f", str(ROOT / f"infra/k8s/examples/evidence-reader-{name}.yaml"))
    kubectl(
        "create",
        "configmap",
        "evidence-check",
        "--namespace",
        NAMESPACE,
        "--from-file=check.py=" + str(ROOT / "scripts/ci/check_cluster_evidence.py"),
    )
    kubectl("apply", "-f", str(ROOT / "infra/kind/crash-fixture.yaml"))


def verify() -> None:
    kubectl("apply", "-f", str(ROOT / "infra/kind/evidence-check-job.yaml"))
    deadline = time.monotonic() + 270
    while time.monotonic() < deadline:
        job = json.loads(
            kubectl(
                "get", "job", "evidence-check", "--namespace", NAMESPACE, "-o", "json", capture=True
            )
        )
        status = job.get("status", {})
        if status.get("failed"):
            raise AssertionError("Isolated evidence-check Job failed; inspect saved diagnostics")
        if status.get("succeeded") == 1:
            output = kubectl("logs", "job/evidence-check", "--namespace", NAMESPACE, capture=True)
            lines = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
            assert any(
                line.get("result") == "passed" and line.get("real_api") is True for line in lines
            )
            print(output, end="")
            return
        time.sleep(3)
    raise AssertionError("Isolated evidence-check Job exceeded deadline")


def diagnostics() -> None:
    base = directory()
    output = base / "diagnostics"
    output.mkdir(exist_ok=True)
    if not owned():
        (output / "state.txt").write_text("No fixture-owned cluster was created.\n")
        return
    commands = {
        "pods.txt": ["get", "pods", "--namespace", NAMESPACE, "-o", "wide"],
        "events.txt": ["get", "events", "--namespace", NAMESPACE],
        "job.txt": ["describe", "job", "evidence-check", "--namespace", NAMESPACE],
        "reader.log": ["logs", "job/evidence-check", "--namespace", NAMESPACE],
    }
    for name, args in commands.items():
        try:
            content = kubectl(*args, capture=True, timeout=30)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            content = type(exc).__name__ + " while collecting fixture diagnostics\n"
        (output / name).write_text(content)


def cleanup() -> None:
    base = directory()
    if owned():
        run([str(base / "bin/kind"), "delete", "cluster", "--name", NAME], timeout=120)
        (base / "owned").unlink()


if __name__ == "__main__":
    actions: dict[str, Any] = {
        "install": install,
        "create": create,
        "verify": verify,
        "diagnostics": diagnostics,
        "cleanup": cleanup,
    }
    if len(sys.argv) != 2 or sys.argv[1] not in actions:
        raise SystemExit("Choose install/create/verify/diagnostics/cleanup")
    actions[sys.argv[1]]()
