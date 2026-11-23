#!/usr/bin/env python3
"""Prepare a new, explicitly owned Linux/WSL2 local trial cluster.

No ambient kube context is read or changed. No existing named cluster is adopted.
This path is separate from the CI runner and never sets fake CI variables.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.ci import local_identity  # noqa: E402


def docker(*args: str) -> str:
    return subprocess.check_output(["docker", *args], text=True, timeout=30).strip()


def preflight() -> dict[str, Any]:
    local_identity.base()  # Validates platform without creating a cluster.
    context = json.loads(docker("context", "inspect"))
    if len(context) != 1:
        raise RuntimeError("Expected one current Docker context")
    endpoint = context[0]["Endpoints"]["docker"]["Host"]
    if not endpoint.startswith("unix://") or os.environ.get("DOCKER_HOST"):
        raise RuntimeError("Use the local Docker Desktop WSL2 Unix socket, not a remote Docker host")
    info = json.loads(docker("info", "--format", "{{json .}}"))
    if info.get("OSType") != "linux" or info.get("Architecture") not in {"x86_64", "amd64"}:
        raise RuntimeError("Local trials require Linux amd64 containers")
    if info.get("MemTotal", 0) < 8 * 1024**3:
        raise RuntimeError("Give Docker at least8GiB RAM for this starting trial configuration")
    if info.get("NCPU", 0) < 4:
        raise RuntimeError("Give Docker at least4CPU cores for this starting configuration")
    if shutil.disk_usage(Path.home()).free < 30 * 1024**3:
        raise RuntimeError("Keep at least30GiB free in the Linux working filesystem")
    compose = docker("compose", "version", "--short")
    if not compose.lstrip("v").startswith(("2.", "3.", "4.", "5.")):
        raise RuntimeError("Docker Compose v2 or newer required")
    return {"docker_cpus": info["NCPU"], "docker_memory_bytes": info["MemTotal"],
            "compose_version": compose, "endpoint": endpoint,
            "not_a_capacity_or_trial_acceptance_result": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "prepare", "up", "hooks", "status", "down"])
    args = parser.parse_args()
    if args.action == "check":
        print(json.dumps(preflight(), indent=2))
        return
    if args.action == "prepare":
        report = preflight()
        # Refuse the name even before downloading tools or recording ownership.
        existing = docker("ps", "-a", "--filter", "name=^/aegis-local-eval-control-plane$", "--format", "{{.ID}}")
        if existing:
            raise RuntimeError("Named node already exists; refusing adoption or deletion")
        local_identity.initialize()
        (local_identity.base() / "preflight.json").write_text(json.dumps(report, indent=2))
    os.environ["AEGIS_LOCAL_EVALUATION"] = "1"
    from scripts.ci import kind_platform_gate as fixture
    if args.action == "prepare":
        fixture.install()
    elif args.action == "up":
        preflight()
        fixture.build()
        fixture.create()
    elif args.action == "hooks":
        if not fixture.owned():
            raise RuntimeError("Refusing unowned cluster")
        fixture.kubectl("set", "env", "deployment/catalog-service", "AEGIS_SHOP_FAULTS_ENABLED=true", "-n", fixture.NS)
        fixture.kubectl("rollout", "status", "deployment/catalog-service", "-n", fixture.NS,
                        "--timeout=180s", timeout=200)
    elif args.action == "status":
        if not fixture.owned():
            raise RuntimeError("Local owner/node identity mismatch")
        print(fixture.kubectl("get", "pods,pvc", "-n", fixture.NS, "-o", "wide", capture=True))
    elif args.action == "down":
        if not fixture.owned():
            raise RuntimeError("Refusing deletion: local owner/node identity mismatch")
        fixture.cleanup()
        print("Only the owned local cluster was deleted. Logs/state retained for review; no Docker prune was run.")


if __name__ == "__main__":
    main()
