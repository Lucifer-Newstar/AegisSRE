"""Record solo human acknowledgements plus fixed independently polled probes.

python -m evaluation.manual OUTPUT --operator NAME --pair-id http-5xx-01

This recorder never injects/restores faults or runs remediation. Keep the human
terminal separate from the blinded controller and preserve the final digest.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from threading import Event, Thread
from uuid import uuid4

from evaluation.capture import fetch
from evaluation.timing import TimingJournal, verify


def record(output: Path, operator: str, pair_id: str, *, port: int = 9001,
           endpoint: str = "/products", maximum_seconds: int = 600) -> None:
    if not operator.strip() or len(operator) > 100 or not pair_id or len(pair_id) > 160:
        raise ValueError("Operator and bounded pair identity required")
    if (port, endpoint) not in {(9001, "/products"), (9002, "/cart/evaluation-probe"), (9003, "/ready")}:
        raise ValueError("Only fixed owned fixture probe boundaries are supported")
    if not 30 <= maximum_seconds <= 1800:
        raise ValueError("Session limit outside30..1800seconds")
    from chaoslab.__main__ import driver
    api = driver()
    output.mkdir(parents=True, exist_ok=False)
    journal = TimingJournal(output / "timing.jsonl")
    stop = Event()
    forwards = api.Forwards()
    worker: Thread | None = None
    failures: list[str] = []
    service = {9001: "catalog-service", 9002: "cart-service", 9003: "order-service"}[port]

    def observe() -> None:
        try:
            while not stop.is_set():
                journal.record("independent_probe", observation=fetch(port, endpoint))
                stop.wait(1)
        except Exception as error:
            failures.append(type(error).__name__)
            stop.set()

    try:
        forwards.start(service, port, port)
        journal.record("session_started", operator=operator, workflow="manual", pair_id=pair_id,
            session_id=uuid4().hex, maximum_seconds=maximum_seconds,
            probe_endpoint=endpoint, probe_service=service,
            caveat="Single operator, unblinded; acknowledgements are not independently certified detection. No automatic outcome inferred.")
        worker = Thread(target=observe, daemon=True)
        worker.start()
        # Timed stop is independent of the terminal input thread. An extra key
        # may be needed to leave the prompt after timeout, never to set its time.
        from threading import Timer
        def timed_out() -> None:
            journal.record("observation_deadline_reached", maximum_seconds=maximum_seconds)
            stop.set()

        timer = Timer(maximum_seconds, timed_out)
        timer.start()
        try:
            print("Recorder active. Commands: detected, action-start, action-done, stop. No fault label is displayed.")
            while not stop.is_set():
                try:
                    command = input("> ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if stop.is_set():
                    break
                if command in {"detected", "action-start", "action-done"}:
                    journal.record("human_acknowledgement", acknowledgement=command, operator=operator)
                elif command == "stop":
                    journal.record("human_session_stop", operator=operator)
                    break
                else:
                    print("Use detected, action-start, action-done, or stop. Free text is not a command.")
        finally:
            timer.cancel()
            timer.join(timeout=5)
    finally:
        stop.set()
        if worker is not None:
            worker.join(timeout=10)
        forwards.close()
        journal.record("recorder_stopped", observer_errors=failures,
                       outcome="not_reviewed", no_remediation_performed_by_recorder=True)
        final = journal.close()
        (output / "final-digest.txt").write_text(final + "\n")
        print("Retain this final digest separately: " + final)
    verify(output / "timing.jsonl", final)
    (output / "review-required.json").write_text(json.dumps({"operator": operator,
        "pair_id": pair_id, "final_sha256": final, "status": "human_review_required",
        "onset_at": None, "detected_at": None, "recovered_at": None,
        "limitations": ["One operator and learning/order effects must be disclosed.",
            "Hash chain checks integrity against retained digest, not authenticity or protection against full-log rewriting.",
            "Probe errors are not automatically fault onset. Review service-specific signals and sustained recovery.",
            "Control cleanup cannot receive remediation credit."]}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--pair-id", required=True)
    parser.add_argument("--boundary", choices=["catalog", "cart", "order"], default="catalog")
    parser.add_argument("--maximum-seconds", type=int, default=600)
    args = parser.parse_args()
    port, path = {"catalog": (9001, "/products"), "cart": (9002, "/cart/evaluation-probe"),
                  "order": (9003, "/ready")}[args.boundary]
    record(args.output, args.operator, args.pair_id, port=port, endpoint=path,
           maximum_seconds=args.maximum_seconds)


if __name__ == "__main__":
    main()
