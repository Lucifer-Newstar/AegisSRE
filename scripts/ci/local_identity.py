"""Explicit local fixture identity, separate from CI and ambient kube contexts."""
from __future__ import annotations

import json
import os
import platform
import subprocess
from pathlib import Path
from uuid import uuid4

LOCAL_NAME = "aegis-local-eval"


def enabled() -> bool:
    return os.environ.get("AEGIS_LOCAL_EVALUATION") == "1"


def base() -> Path:
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise RuntimeError("Local evaluation currently requires Linux x86_64, including WSL2")
    return Path.home() / ".local/state/aegissre-evaluation"


def initialize() -> str:
    root = base()
    root.mkdir(parents=True, exist_ok=True)
    marker = root / "local-owner.json"
    if marker.exists():
        raise RuntimeError("Existing local fixture state requires inspection; refusing takeover")
    identity = uuid4().hex
    with marker.open("x") as output:
        json.dump({"schema": "local-owner-1", "owner": identity, "cluster": LOCAL_NAME}, output)
    return identity


def owner() -> str:
    marker = base() / "local-owner.json"
    if marker.is_symlink() or marker.stat().st_size > 1024:
        raise RuntimeError("Invalid local ownership record")
    value = json.loads(marker.read_text())
    identity = value.get("owner", "")
    if value.get("cluster") != LOCAL_NAME or len(identity) != 32 or any(c not in "0123456789abcdef" for c in identity):
        raise RuntimeError("Invalid local identity")
    return str(identity)


def node_identity() -> str:
    # Local named node only. No ambient kubectl context, remote URL or caller name.
    value = subprocess.check_output(["docker", "inspect", "--format", "{{json .}}",
                                     LOCAL_NAME + "-control-plane"], text=True, timeout=10)
    node = json.loads(value)
    if node.get("Config", {}).get("Labels", {}).get("io.x-k8s.kind.cluster") != LOCAL_NAME:
        raise RuntimeError("Node does not have the expected kind cluster label")
    identity = node.get("Id", "")
    if len(identity) != 64 or any(c not in "0123456789abcdef" for c in identity):
        raise RuntimeError("Invalid local node identity")
    return str(identity)


def record_node() -> None:
    with (base() / "local-node-id").open("x") as output:
        output.write(node_identity())


def verify_node() -> bool:
    marker = base() / "local-node-id"
    if not marker.is_file() or marker.is_symlink():
        return False
    return marker.read_text() == node_identity()
