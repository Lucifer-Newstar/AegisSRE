"""Run one frozen, bounded workflow with separately marked cleanup.

No recovery/correctness claim is inferred. No policy or plan is manufactured.
python -m evaluation.session MANIFEST OUTPUT --pair-id http-5xx-01 --workflow manual --operator Navin
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any

from chaoslab.__main__ import ROOT
from evaluation.capture import canonical, digest, fetch, validate_manifest
from evaluation.timing import TimingJournal, verify


def select_trial(manifest: dict[str, Any], pair: str, workflow: str) -> str:
    rows = [r for r in manifest["inputs"]["schedule"] if r["pair_id"] == pair]
    if len(rows) != 1 or workflow not in rows[0]["workflows"]:
        raise ValueError("Pair/workflow is outside frozen schedule")
    return str(rows[0]["fault"])


def run(manifest_path: Path, output: Path, pair: str, workflow: str, operator: str,
        *, fault_seconds: int = 120, warmup_seconds: int = 180) -> None:
    if workflow not in {"manual", "aegis"} or not operator.strip() or len(operator) > 100:
        raise ValueError("Explicit workflow and operator required")
    if not 10 <= warmup_seconds <= 600:
        raise ValueError("Warm-up outside10..600seconds")
    if not 15 <= fault_seconds <= 120:
        raise ValueError("Bounded fault window must be15..120seconds")
    manifest = validate_manifest(manifest_path)
    fault = select_trial(manifest, pair, workflow)
    from chaoslab.__main__ import driver
    api = driver()
    service, port, endpoint = {
        "database-outage": ("order-service", 9003, "/ready"),
        "dependency-failure": ("cart-service", 9002, "/cart/evaluation-probe"),
    }.get(fault, ("catalog-service", 9001, "/products"))
    lock = api.directory() / "comparison-active"
    # Stale locks require inspection. Never silently adopt an interrupted session.
    with lock.open("x") as marker:
        marker.write(api.owner())
    # Any failure deliberately retains the lock for inspection.
    _session(api, manifest_path, manifest, output, pair, workflow, operator,
             fault, service, port, endpoint, fault_seconds, warmup_seconds)
    lock.unlink()


def _session(api: Any, manifest_path: Path, manifest: dict[str, Any], output: Path,
             pair: str, workflow: str, operator: str, fault: str, service: str,
             port: int, endpoint: str, fault_seconds: int, warmup_seconds: int) -> None:
    output.mkdir(parents=True, exist_ok=False)
    (output / "manifest.json").write_bytes(manifest_path.read_bytes())
    environment = json.loads(api.kubectl("get", "deployment,statefulset,pods", "-n", api.NS,
                                        "-o", "json", capture=True))
    (output / "environment.json").write_text(json.dumps(environment, indent=2))
    journal = TimingJournal(output / "timing.jsonl")
    forwards = api.Forwards()
    stop = Event()
    process: subprocess.Popen[str] | None = None
    sampler: Thread | None = None
    errors: list[str] = []
    control_rows_seen = 0
    load_workers: list[Thread] = []
    acknowledgement_lock = Lock()
    request: Any = None

    def load() -> None:
        # Identical closed-loop load configuration for both workflows and all fault windows.
        # Network failures are observations, never silently called recovery.
        while not stop.is_set():
            fetch(port, endpoint)
            stop.wait(0.1)

    def cluster_observe() -> None:
        try:
            while not stop.is_set():
                raw = api.kubectl("get", "deployment,statefulset,pods,events", "-n", api.NS,
                                  "-o", "json", capture=True, timeout=20)
                journal.record("independent_kubernetes_snapshot", objects=json.loads(raw))
                stop.wait(5)
        except Exception as error:
            errors.append(type(error).__name__)
            stop.set()

    def observe() -> None:
        try:
            while not stop.is_set():
                journal.record("observation", service=service,
                    domain=fetch(port, endpoint), metrics=fetch(port, "/metrics"),
                    incidents=fetch(8201, f"/incidents?service={service}&limit=100", authenticated=True),
                    anomalies=fetch(8201, f"/events?service={service}&environment=dev&event_type=anomaly&limit=100", authenticated=True))
                if fetch(port, endpoint)["status"] is None:
                    # A replaced Pod invalidates kubectl port-forward. Reconnect
                    # read plumbing only, never replay an application write.
                    forwards.start(service, port, port)
                    journal.record("probe_forward_restarted", measurement_gap=True)
                stop.wait(1)
        except Exception as error:
            errors.append(type(error).__name__)
            stop.set()

    def acknowledge() -> None:
        while not stop.is_set():
            try:
                command = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                return
            with acknowledgement_lock:
                if not stop.is_set() and command in {"detected", "action-start", "action-done"}:
                    journal.record("human_acknowledgement", operator=operator, acknowledgement=command)

    def ingest_control() -> None:
        nonlocal control_rows_seen
        files = list((output / "control").glob("run-*.jsonl"))
        if len(files) > 1:
            raise RuntimeError("Unexpected multiple controller journals")
        if files:
            rows = files[0].read_text().splitlines()
            for line in rows[control_rows_seen:]:
                try:
                    value = json.loads(line)
                except ValueError:
                    break  # Next poll reads the incomplete last line again.
                journal.record("controller_boundary", control=value,
                    not_independent_symptom_time=True,
                    cleanup_excludes_later_remediation_credit=value["stage"] in {
                        "load_completed", "restoration_requested", "restored_control_state", "restoration_failed"})
                control_rows_seen += 1

    try:
        forwards.start(service, port, port)
        forwards.start("incidents-service", 8201, 8201)
        os.environ.update(api.FIXTURE)
        sys.path.insert(0, str(ROOT / "scripts"))
        from scripts.check_gateway_stack import request as gateway_request
        from scripts.check_runtime_stack import wait_for
        request = gateway_request
        forwards.start("api-gateway", 8080, 8000)
        wait_for(lambda: fetch(port, endpoint)["status"] == 200, "healthy probe before session", 60)
        before = wait_for(lambda: request("/api/v1/autonomy"), "runtime mode before session", 60)
        if workflow == "aegis" and before["executor"] != "kubernetes":
            raise RuntimeError("Aegis trials require the actual deployed Kubernetes executor")
        baseline_incidents = request("/api/v1/incidents?limit=500")
        if workflow == "aegis" and any(item["status"] not in {"closed", "escalated"}
                                       for item in baseline_incidents):
            raise RuntimeError("Active incident carryover: isolate/reset the owned trial baseline first")
        journal.record("baseline_incidents", incidents=baseline_incidents,
                       carryover_requires_review=True)
        # Manual blocks all platform execution. Aegis uses actual existing policy,
        # never a seeded winning plan or policy override. Default policy may escalate.
        mode = "observe" if workflow == "manual" else "auto-safe"
        request("/api/v1/autonomy", body={"mode": mode, "actor": "evaluation-session"})
        journal.record("session_started", pair_id=pair, workflow=workflow, operator=operator,
            policy_before=before["policy"], mode_during=mode, fault_seconds=fault_seconds,
            warmup_seconds=warmup_seconds, closed_loop_load_workers=4, pause_per_worker_seconds=0.1,
            environment_sha256=canonical(environment), inputs_sha256=manifest["inputs_sha256"],
            source_revision=manifest["inputs"]["source_revision"],
            limitations=["One operator, non-blinded, small sample, learning/order effects.",
                "All outcomes require independent fault-specific review.",
                "No recovery after controller cleanup receives workflow credit."])
        sampler = Thread(target=observe, daemon=True)
        sampler.start()
        if workflow == "manual":
            print("Actual manual session. Use monitoring and perform the fix yourself. Mark detected/action-start/action-done here.")
            Thread(target=acknowledge, daemon=True).start()
        cluster_worker = Thread(target=cluster_observe, daemon=True)
        cluster_worker.start()
        load_workers.append(cluster_worker)
        for _ in range(4):
            worker = Thread(target=load, daemon=True)
            worker.start()
            load_workers.append(worker)
        if stop.wait(warmup_seconds):
            raise RuntimeError("Observer stopped during warm-up")
        journal.record("warmup_finished",
            runtime=fetch(8201, "/runtime", authenticated=True),
            detector_warmup_not_certified=True)
        (output / "control").mkdir()
        with (output / "controller.log").open("w") as log:
            process = subprocess.Popen([sys.executable, "-m", "chaoslab", fault,
                "--seconds", str(fault_seconds), "--output", str(output / "control")],
                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, text=True)
            deadline = time.monotonic() + fault_seconds + 600
            while process.poll() is None:
                ingest_control()
                if errors or time.monotonic() >= deadline:
                    raise RuntimeError("Observer failed or controller deadline exceeded")
                time.sleep(0.2)
            ingest_control()
            if process.returncode:
                raise RuntimeError("Fault controller failed; retain failed/partial session")
        journal.record("control_finished", safety_cleanup_not_workflow_recovery=True)
        stop.wait(30)
        if errors:
            raise RuntimeError("Observer failed")
    finally:
        try:
            # Block new Aegis actions BEFORE controller safety cleanup. A failed
            # mode request is not silently ignored or replayed.
            if request is not None:
                request("/api/v1/autonomy", body={"mode": "observe", "actor": "evaluation-safety-stop"})
        finally:
            try:
                if process is not None and process.poll() is None:
                    process.terminate()
                    process.wait(timeout=240)  # Controller finally restores, never credited.
                    ingest_control()
            finally:
                with acknowledgement_lock:
                    stop.set()
                workers = [*load_workers, *([sampler] if sampler else [])]
                for worker in workers:
                    worker.join(timeout=25)
                if any(worker.is_alive() for worker in workers):
                    errors.append("observer_did_not_stop")
                forwards.close()
                journal.record("session_stopped", observer_errors=errors, reviewed=False)
                final = journal.close()
                (output / "final-digest.txt").write_text(final + "\n")
                print("Retain final digest separately: " + final)
    if errors:
        raise RuntimeError("Incomplete observation: " + errors[0])
    verify(output / "timing.jsonl", final)
    (output / "review-required.json").write_text(json.dumps({
        "status": "human_review_required", "pair_id": pair, "workflow": workflow,
        "operator": operator, "final_sha256": final, "onset_at": None,
        "detected_at": None, "recovered_at": None,
        "controller_cleanup_is_censoring_boundary": True,
        "not_benchmark_acceptance": True}, indent=2))
    (output / "session-index.json").write_text(json.dumps({
        "schema_version": "matched-session-1", "status": "captured_not_reviewed",
        "files": {p.relative_to(output).as_posix(): digest(p)
                  for p in sorted(output.rglob("*")) if p.is_file()},
        "final_sha256": final}, indent=2))



def main() -> None:
    def interrupted(signum: int, frame: Any) -> None:
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--pair-id", required=True)
    parser.add_argument("--workflow", choices=["manual", "aegis"], required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--fault-seconds", type=int, default=120)
    parser.add_argument("--warmup-seconds", type=int, default=180)
    args = parser.parse_args()
    run(args.manifest, args.output, args.pair_id, args.workflow, args.operator,
        fault_seconds=args.fault_seconds, warmup_seconds=args.warmup_seconds)


if __name__ == "__main__":
    main()
