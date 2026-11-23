"""Freeze local inputs and capture raw owned-cluster trials, never certify results.

python -m evaluation.capture freeze MANIFEST --corpus DIRECTORY
python -m evaluation.capture trial MANIFEST OUTPUT --fault http-5xx --seconds 30
"""
from __future__ import annotations

import argparse
import hashlib
import json
import signal
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread
from typing import Any
from urllib.parse import urlsplit

from chaoslab.__main__ import ROOT, driver, run
from chaoslab.journal import Journal
from evaluation.report import FAULTS

MAX_BYTES = 1_000_000


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_files(root: Path) -> dict[str, str]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Expected a real directory")
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Frozen inputs cannot contain symlinks")
        if path.is_file():
            if path.stat().st_size > MAX_BYTES:
                raise ValueError("Frozen file exceeds1MB")
            files[path.relative_to(root).as_posix()] = digest(path)
    if not files or len(files) > 1000:
        raise ValueError("Frozen directory must contain1..1000 bounded files")
    return files


def canonical(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def revision() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def source_clean() -> bool:
    return not subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=normal"],
                                       cwd=ROOT, text=True).strip()


def freeze(path: Path, corpus: Path) -> None:
    if not source_clean():
        raise ValueError("Commit source changes before freezing an experiment")
    inputs: dict[str, Any] = {
        "source_revision": revision(), "corpus_root": str(corpus.resolve()),
        "corpus_files": tree_files(corpus),
        "workload_files": tree_files(ROOT / "infra/k8s"),
        "reporting_semantics": "raw capture only; human review required before held_out reporting",
        "schedule": [{"pair_id": f"{fault}-{repeat:02d}", "fault": fault,
                      "workflows": ["manual", "aegis"]}
                     for fault in sorted(FAULTS) for repeat in range(1, 11)],
    }
    manifest = {"schema_version": "capture-1", "frozen_at": datetime.now(UTC).isoformat(),
                "inputs": inputs, "inputs_sha256": canonical(inputs)}
    with path.open("x") as output:
        json.dump(manifest, output, indent=2)
        output.write("\n")


def validate_manifest(path: Path) -> dict[str, Any]:
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("Manifest exceeds1MB")
    manifest: dict[str, Any] = json.loads(path.read_text())
    inputs = manifest["inputs"]
    if manifest["schema_version"] != "capture-1" or canonical(inputs) != manifest["inputs_sha256"]:
        raise ValueError("Manifest digest/schema mismatch")
    if not source_clean() or inputs["source_revision"] != revision():
        raise ValueError("Source changed since freeze")
    if tree_files(Path(inputs["corpus_root"])) != inputs["corpus_files"]:
        raise ValueError("Frozen corpus changed")
    if tree_files(ROOT / "infra/k8s") != inputs["workload_files"]:
        raise ValueError("Frozen workload manifests changed")
    return manifest


def fetch(port: int, path: str, *, authenticated: bool = False) -> dict[str, Any]:
    # Fixed localhost fixture destinations only. No redirects, cookies or caller URLs.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req: Any, fp: Any, code: int, msg: str,
                             headers: Any, newurl: str) -> None:
            return None

    if port not in {8201, 9001} or urlsplit(path).scheme or not path.startswith("/") or path.startswith("//"):
        raise ValueError("Only fixed owned-fixture endpoints are accepted")
    headers = {"Accept": "application/json"}
    if authenticated:
        from scripts.ci.kind_platform_gate import FIXTURE
        headers["Authorization"] = "Bearer " + FIXTURE["AEGIS_API_TOKEN"]
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    started = time.monotonic()
    try:
        try:
            response = opener.open(request, timeout=3)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("Response exceeds1MB")
            try:
                body: Any = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                body = raw.decode("utf-8", errors="replace")
            return {"observed_at": datetime.now(UTC).isoformat(), "status": response.code, "elapsed_seconds": time.monotonic() - started,
                    "body": body}
    except (OSError, ValueError) as error:
        return {"observed_at": datetime.now(UTC).isoformat(), "status": None, "error_type": type(error).__name__,
                "elapsed_seconds": time.monotonic() - started}


def trial(manifest_path: Path, output: Path, fault: str, seconds: int, repeat: int) -> None:
    if fault not in FAULTS or not 1 <= seconds <= 120 or not 1 <= repeat <= 10:
        raise ValueError("Unsupported fault, duration or repetition")
    manifest = validate_manifest(manifest_path)
    api = driver()  # Fails before writes unless this run owns the disposable fixture.
    output.mkdir(parents=True, exist_ok=False)
    # Save real environment state, not a declaration that paired runs are identical.
    environment = json.loads(api.kubectl("get", "deployment,statefulset,pods", "-n", api.NS,
                                         "-o", "json", capture=True))
    (output / "environment.json").write_text(json.dumps(environment, indent=2))
    (output / "manifest.json").write_bytes(manifest_path.read_bytes())
    journal = Journal(output, "observations")
    stop = Event()
    forwards = api.Forwards()
    worker: Thread | None = None
    errors: list[str] = []

    def collect() -> None:
        try:
            while not stop.is_set():
                journal.record("sample", observed_at=datetime.now(UTC).isoformat(),
                    domain=fetch(9001, "/products"),
                    metrics=fetch(9001, "/metrics"),
                    incidents=fetch(8201, "/incidents?service=catalog-service&limit=100",
                                    authenticated=True))
                stop.wait(2)
        except BaseException as error:
            errors.append(type(error).__name__)
            stop.set()

    try:
        forwards.start("catalog-service", 9001, 9001)
        forwards.start("incidents-service", 8201, 8201)
        for _ in range(30):
            domain = fetch(9001, "/products")
            incidents = fetch(8201, "/incidents?service=catalog-service&limit=100", authenticated=True)
            if domain["status"] == 200 and incidents["status"] == 200:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Healthy domain and platform baseline unavailable")
        journal.record("capture_started", fault=fault, workflow="aegis",
            pair_id=f"{fault}-{repeat:02d}", inputs_sha256=manifest["inputs_sha256"],
            environment_sha256=canonical(environment),
            caveat="Sample times are read times, not certified onset/detection/recovery. Chaos restoration is not autonomous remediation.")
        worker = Thread(target=collect, daemon=True)
        worker.start()
        time.sleep(10)
        run(fault, seconds, output / "control")
        # Continue after control restoration so recovery observations are retained.
        stop.wait(30)
        if errors:
            raise RuntimeError("Capture observer failed: " + errors[0])
    finally:
        stop.set()
        try:
            if worker is not None:
                worker.join(timeout=15)
                if worker.is_alive():
                    raise RuntimeError("Observer did not stop")
        finally:
            forwards.close()
            journal.close()
    (output / "capture.json").write_text(json.dumps({"schema_version": "capture-1",
        "status": "captured_not_reviewed", "fault": fault, "workflow": "aegis",
        "pair_id": f"{fault}-{repeat:02d}",
        "files": {p.relative_to(output).as_posix(): digest(p)
                  for p in sorted(output.rglob("*")) if p.is_file()},
        "limitations": ["No manual observer or baseline generated.",
            "No outcome, MTTD, MTTR, eligibility or cause correctness inferred.",
            "Source revision and file hashes are verified; environment equivalence needs review.",
            "Fault labels/control journals are separate from read-only platform observations."]}, indent=2))


def main() -> None:
    def interrupted(signum: int, frame: Any) -> None:
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    frozen = commands.add_parser("freeze")
    frozen.add_argument("manifest", type=Path)
    frozen.add_argument("--corpus", type=Path, required=True)
    capture = commands.add_parser("trial")
    capture.add_argument("manifest", type=Path)
    capture.add_argument("output", type=Path)
    capture.add_argument("--fault", choices=sorted(FAULTS), required=True)
    capture.add_argument("--seconds", type=int, default=30)
    capture.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(args.manifest, args.corpus)
    else:
        trial(args.manifest, args.output, args.fault, args.seconds, args.repeat)


if __name__ == "__main__":
    main()
