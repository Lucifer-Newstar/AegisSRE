#!/usr/bin/env python3
"""Prepare a new, explicitly owned Linux/WSL2 local trial cluster.

No ambient kube context is read or changed. No existing named cluster is adopted.
This path is separate from the CI runner and never sets fake CI variables.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

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


def reset_owned(*, confirmed: bool) -> Path:
    """Archive the whole old fixture, then build a fresh owned baseline.

    Never wipe database tables, reset detector internals, adopt a node, reuse an
    identity or prune Docker. Reuses existing image layers and verified binaries.
    """
    if not confirmed:
        raise RuntimeError("Reset deletes only this owned cluster; pass --confirm-owned-reset")
    preflight()
    os.environ["AEGIS_LOCAL_EVALUATION"] = "1"
    from scripts.ci import kind_platform_gate as fixture
    if not fixture.owned():
        raise RuntimeError("Refusing reset: owner/node identity mismatch")
    root = local_identity.base()
    for name in ("comparison-active", "chaos-active"):
        if (root / name).exists():
            raise RuntimeError("Interrupted/active experiment needs inspection before reset")
    # Preserve source identity and diagnostics before any destructive step.
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Commit source before resetting a comparative baseline")
    pins = json.loads((ROOT / "infra/kind/ci-versions.json").read_text())
    for tool in ("kind", "kubectl"):
        binary = root / "bin" / tool
        if binary.is_symlink() or hashlib.sha256(binary.read_bytes()).hexdigest() != pins[tool + "_sha256"]:
            raise RuntimeError("Owned fixture binary no longer matches the pinned checksum")
    fixture.diagnostics()
    (root / "reset-source.json").write_text(json.dumps({"source_revision": source,
        "previous_owner": local_identity.owner(), "previous_node": local_identity.node_identity(),
        "not_environment_equivalence_certification": True}, indent=2))
    fixture.cleanup()  # Rechecks ownership, deletes only the matching named node.
    if docker("ps", "-a", "--filter", "name=^/aegis-local-eval-control-plane$", "--format", "{{.ID}}"):
        raise RuntimeError("Owned node still present after cleanup; refusing fresh creation")
    archive = root.with_name(root.name + "-archive-" + uuid4().hex)
    root.rename(archive)
    local_identity.initialize()  # New identity, never continue the old one.
    shutil.copytree(archive / "bin", root / "bin")
    fixture.create()  # Fresh DB PVCs, Pod UIDs, telemetry and detector state.
    fixture.kubectl("set", "env", "deployment/catalog-service", "AEGIS_SHOP_FAULTS_ENABLED=true", "-n", fixture.NS)
    fixture.kubectl("rollout", "status", "deployment/catalog-service", "-n", fixture.NS,
                    "--timeout=180s", timeout=200)
    from scripts.enable_scoped_executor import enable
    enable()  # Same restricted executor for BOTH sides, observe until session.
    (root / "fresh-baseline.json").write_text(json.dumps({"source_revision": source,
        "archived_fixture": str(archive), "new_owner": local_identity.owner(),
        "new_node": local_identity.node_identity(), "policy_unchanged": True,
        "review_still_required": True}, indent=2))
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "prepare", "up", "hooks", "status", "down", "reset"])
    parser.add_argument("--confirm-owned-reset", action="store_true")
    args = parser.parse_args()
    if args.action == "reset":
        print("Archived old fixture: " + str(reset_owned(confirmed=args.confirm_owned_reset)))
        return
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
