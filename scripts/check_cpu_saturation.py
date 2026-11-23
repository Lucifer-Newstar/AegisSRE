#!/usr/bin/env python3
"""Measure sustained application CPU against the owned demo's fixed cgroup quota."""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/ci"))
import kind_platform_gate as fixture  # noqa: E402


def cpu() -> float:
    with urllib.request.urlopen("http://127.0.0.1:9001/metrics", timeout=10) as response:
        lines = response.read(1000000).decode().splitlines()
    return next(float(line.split()[1]) for line in lines
                if line.startswith("process_cpu_seconds_total "))


def main() -> None:
    if not fixture.owned():
        raise RuntimeError("Refusing unowned cluster")
    deployment = json.loads(fixture.kubectl("get", "deployment/catalog-service", "-n", fixture.NS,
                                           "-o", "json", capture=True))
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    if container["resources"]["limits"]["cpu"] != "200m":
        raise RuntimeError("Saturation proof requires the fixed200m demo CPU quota")
    forwards = fixture.Forwards()
    stop = Event()
    pool = ThreadPoolExecutor(max_workers=4)
    experiment: subprocess.Popen[str] | None = None
    output = fixture.directory() / "diagnostics" / "sustained-cpu"
    output.mkdir(exist_ok=True)

    def traffic() -> None:
        while not stop.is_set():
            try:
                with urllib.request.urlopen("http://127.0.0.1:9001/products", timeout=5) as response:
                    response.read(65536)
            except OSError:
                pass
            stop.wait(0.02)

    try:
        forwards.start("catalog-service", 9001, 9001)
        for _ in range(30):
            try:
                before = cpu()
                break
            except OSError:
                time.sleep(0.2)
        else:
            raise RuntimeError("Metrics forward unavailable")
        started = time.monotonic()
        time.sleep(5)
        baseline = (cpu() - before) / (time.monotonic() - started)
        with (output / "runner.log").open("w") as log:
            experiment = subprocess.Popen([sys.executable, "-m", "chaoslab", "cpu-saturation",
                "--seconds", "40", "--output", str(output)], cwd=ROOT,
                stdout=log, stderr=subprocess.STDOUT, text=True)
            for _ in range(4):
                pool.submit(traffic)
            time.sleep(5)
            samples: list[dict[str, Any]] = []
            for _ in range(4):
                before, started = cpu(), time.monotonic()
                time.sleep(5)
                after, finished = cpu(), time.monotonic()
                consumed, elapsed = after - before, finished - started
                samples.append({"cpu_seconds": consumed, "elapsed_seconds": elapsed,
                    "quota_cores": 0.2, "quota_utilization": consumed / elapsed / 0.2})
            assert all(row["quota_utilization"] >= 0.7 for row in samples), samples
            assert experiment.wait(timeout=90) == 0
        stop.set()
        pool.shutdown(wait=True)
        with urllib.request.urlopen("http://127.0.0.1:9001/products", timeout=10) as response:
            assert response.status == 200
        (output / "independent-proof.json").write_text(json.dumps({
            "workload_uid": deployment["metadata"]["uid"], "baseline_cores": baseline,
            "samples": samples, "minimum_quota_utilization": 0.7,
            "sustained_sample_intervals": 4, "restored_domain_status": 200,
            "not_detector_or_capacity_acceptance": True,
            "caveat": "Application process CPU relative to fixed200m cgroup quota under bounded request load. Not host saturation or production capacity.",
        }, indent=2))
    finally:
        stop.set()
        pool.shutdown(wait=True)
        if experiment is not None and experiment.poll() is None:
            experiment.terminate()
            experiment.wait(timeout=60)
        forwards.close()
    print("Observed sustained application CPU quota utilization and restored domain response")


if __name__ == "__main__":
    main()
