"""Integrity-checked local timing journal. Not an independent timestamp authority."""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any


def encoded(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


class TimingJournal:
    def __init__(self, path: Path):
        self.source = path.open("x", encoding="utf-8")
        self.started = time.monotonic_ns()
        self.previous = "0" * 64
        self.sequence = 0
        self.lock = Lock()

    def record(self, kind: str, **fields: Any) -> str:
        with self.lock:
            value = {"sequence": self.sequence, "previous_sha256": self.previous,
                     "wall_at": datetime.now(UTC).isoformat(),
                     "elapsed_ns": time.monotonic_ns() - self.started,
                     "kind": kind, "data": fields}
            digest = hashlib.sha256(encoded(value)).hexdigest()
            self.source.write(encoded({**value, "sha256": digest}).decode() + "\n")
            self.source.flush()
            os.fsync(self.source.fileno())
            self.previous = digest
            self.sequence += 1
            return digest

    def close(self) -> str:
        with self.lock:
            self.source.close()
            return self.previous


def verify(path: Path, expected_final: str) -> int:
    if path.stat().st_size > 32_000_000:
        raise ValueError("Timing journal exceeds32MB")
    previous = "0" * 64
    elapsed = -1
    count = 0
    for line in path.read_text().splitlines():
        value = json.loads(line)
        claimed = value.pop("sha256")
        if (value["sequence"] != count or value["previous_sha256"] != previous
                or value["elapsed_ns"] < elapsed or hashlib.sha256(encoded(value)).hexdigest() != claimed):
            raise ValueError("Timing journal integrity/ordering failure")
        elapsed, previous, count = value["elapsed_ns"], claimed, count + 1
    if not count or previous != expected_final:
        raise ValueError("Journal does not match retained final digest")
    return count
