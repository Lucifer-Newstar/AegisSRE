#!/usr/bin/env python3
"""Actual opt-in HTTP fault, scraped burn and sustained firing alert in owned CI.

The 1h selector may cover less than one hour in a fresh runner. No full-window
budget or long-term availability claim is made by this experiment.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/ci"))
import kind_platform_gate as fixture  # noqa: E402


def read(path: str) -> dict:
    with urllib.request.urlopen("http://127.0.0.1:19090" + path, timeout=10) as response:
        return json.load(response)


def main() -> None:
    if not fixture.owned():
        raise RuntimeError("Refusing unowned cluster")
    output = fixture.directory() / "diagnostics" / "live-slo-burn"
    output.mkdir(exist_ok=True)
    forwards = fixture.Forwards()
    stop = Event()
    counts = {"200": 0, "503": 0, "other": 0}

    def traffic() -> None:
        while not stop.is_set():
            status = "other"
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:9001/products", timeout=3
                ) as response:
                    status = str(response.status)
            except urllib.error.HTTPError as exc:
                status = str(exc.code)
            except OSError:
                pass
            counts[status if status in counts else "other"] += 1
            stop.wait(0.05)

    worker = Thread(target=traffic)
    started = datetime.now(UTC).isoformat()
    try:
        forwards.start("prometheus", 19090, 9090)
        forwards.start("catalog-service", 9001, 9001)
        deadline = time.monotonic() + 60
        while True:
            try:
                assert read("/api/v1/query?query=up")["status"] == "success"
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(1)
        worker.start()
        with (output / "runner.log").open("w") as log:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "chaoslab",
                    "http-5xx",
                    "--seconds",
                    "120",
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                check=True,
                timeout=200,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        assert counts["503"] >= 100, counts
        deadline = time.monotonic() + 150
        firing = None
        while time.monotonic() < deadline:
            alerts = read("/api/v1/alerts")["data"]["alerts"]
            firing = next(
                (
                    row
                    for row in alerts
                    if row["labels"].get("alertname") == "AegisShopRequestErrorBudgetFastBurn"
                    and row["labels"].get("service") == "catalog-service"
                    and row["state"] == "firing"
                ),
                None,
            )
            if firing:
                break
            time.sleep(2)
        assert firing, "Actual fast-burn alert did not reach firing"
        expr = 'aegisshop:slo_burn_rate:5m{service="catalog-service",environment="dev"}'
        series = read("/api/v1/query?" + urllib.parse.urlencode({"query": expr}))["data"]["result"]
        assert len(series) == 1 and float(series[0]["value"][1]) > 14.4
        with urllib.request.urlopen("http://127.0.0.1:9001/products", timeout=5) as response:
            assert response.status == 200
        (output / "independent-proof.json").write_text(
            json.dumps(
                {
                    "started_at": started,
                    "observed_at": datetime.now(UTC).isoformat(),
                    "observed_responses": counts,
                    "actual_alert": firing,
                    "actual_burn_series": series,
                    "domain_restored": True,
                    "fault_seconds": 120,
                    "full_one_hour_coverage": False,
                    "not_evaluation_accuracy": True,
                    "note": "Real scraped error burn and 2min pending-to-firing rule, not full-window budget acceptance",
                },
                indent=2,
            )
        )
        print(
            "Actual HTTP errors, scraped burn and firing fast-burn alert observed; domain restored. No full-hour budget claim."
        )
    finally:
        stop.set()
        if worker.ident is not None:
            worker.join(timeout=5)
        forwards.close()


if __name__ == "__main__":
    main()
