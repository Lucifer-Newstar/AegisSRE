"""A3: deterministic statistical baselines plus Isolation Forest novelty detection.

Models train on preceding accepted-normal samples only, separately per service,
environment, metric, unit and label set. No generated labels or evaluation truth
are used by the detector. Cold starts return no verdict until 12 samples exist.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from sklearn.ensemble import IsolationForest  # type: ignore[import-untyped]


@dataclass(frozen=True)
class Verdict:
    anomalous: bool
    ready: bool
    mean: float
    std: float
    z_score: float
    isolation_score: float
    score: float


def detect(history: list[float], value: float, *, two_sided: bool = True) -> Verdict:
    if len(history) < 12:
        return Verdict(False, False, 0.0, 0.0, 0.0, 0.0, 0.0)
    window = history[-60:]
    median = statistics.median(window)
    mad = statistics.median(abs(x - median) for x in window)
    # The floor prevents jitter around a flat/zero baseline from exploding scores.
    scale = max(mad * 1.4826, abs(median) * 0.05, 0.001)
    z = (value - median) / scale
    model = IsolationForest(
        n_estimators=50, max_samples=len(window), contamination="auto", random_state=42, n_jobs=1
    )
    model.fit([[x] for x in window])
    isolation_score = float(model.decision_function([[value]])[0])
    distance = abs(z) if two_sided else z
    anomalous = distance >= 4 or (distance >= 2.5 and isolation_score < -0.02)
    score = 1 - math.exp(-max(0.0, distance) / 4)
    return Verdict(
        anomalous,
        True,
        statistics.mean(window),
        statistics.pstdev(window),
        z,
        isolation_score,
        score,
    )


def upper_bound_metric(name: str) -> bool:
    return any(part in name for part in ("latency", "duration", "error", "cpu", "memory", "burn"))
