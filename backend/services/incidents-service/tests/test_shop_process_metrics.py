import importlib
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient


@pytest.mark.parametrize("service", ["catalog", "cart", "order", "payment"])
def test_each_shop_service_exposes_real_process_cpu_and_memory(service: str) -> None:
    module = importlib.import_module(f"{service}_service.main")
    response = TestClient(module.app).get("/metrics")
    assert response.status_code == 200
    values = {}
    for line in response.text.splitlines():
        if line.startswith(("process_cpu_seconds_total ", "process_resident_memory_bytes ")):
            name, value = line.split()
            values[name] = float(value)
    assert values["process_cpu_seconds_total"] >= 0
    assert values["process_resident_memory_bytes"] > 0
    config = yaml.safe_load(
        (Path(__file__).resolve().parents[4] / "infra/prometheus/prometheus.yml").read_text()
    )
    job = next(
        item for item in config["scrape_configs"] if item["job_name"] == f"aegisshop-{service}"
    )
    assert job["static_configs"][0]["labels"] == {
        "service": f"{service}-service",
        "environment": "dev",
    }
