"""Bounded experiment journals. Ground truth is never fabricated telemetry."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class Journal:
    def __init__(self, directory: Path, experiment_id: str):
        if not experiment_id or len(experiment_id) > 80 or any(
            char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            for char in experiment_id
        ):
            raise ValueError("Experiment ID must be a bounded filename-safe identifier")
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / (experiment_id + ".jsonl")
        # Never silently overwrite or append to another experiment's truth.
        self.source = self.path.open("x", encoding="utf-8")
        self.failed = False

    def record(self, stage: str, **fields: Any) -> None:
        entry = {"recorded_at": datetime.now(UTC).isoformat(), "stage": stage, **fields}
        self.source.write(json.dumps(entry, allow_nan=False, sort_keys=True) + "\n")
        self.source.flush()
        os.fsync(self.source.fileno())

    def close(self) -> None:
        self.source.close()
