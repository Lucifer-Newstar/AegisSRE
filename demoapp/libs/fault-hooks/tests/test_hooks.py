from __future__ import annotations

import json
import os
import time
from pathlib import Path

import aegisshop_faults as hooks
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def control(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "fault.json"
    monkeypatch.setattr(hooks, "CONTROL_PATH", path)
    return path


def write(path: Path, **changes: object) -> None:
    value = {"kind": "http-5xx", "until": time.time() + 30, "magnitude": 100, **changes}
    path.write_text(json.dumps(value))


def app() -> FastAPI:
    application = FastAPI()

    @application.get("/products")
    def products() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "healthy"}

    hooks.configure_fault_hooks(application)
    return application


def test_disabled_default_never_reads_or_exposes_control(control: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AEGIS_SHOP_FAULTS_ENABLED", raising=False)
    write(control)
    client = TestClient(app())
    assert client.get("/products").status_code == 200
    assert client.post("/faults", json={"kind": "http-5xx"}).status_code == 404


def test_real_request_fault_expiry_and_restore(control: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AEGIS_SHOP_FAULTS_ENABLED", "true")
    client = TestClient(app())
    write(control)
    assert client.get("/products").status_code == 503
    assert client.get("/health").status_code == 200
    assert client.post("/faults").status_code == 404
    write(control, until=time.time() - 1)
    assert client.get("/products").status_code == 200
    write(control)
    control.unlink()
    assert client.get("/products").status_code == 200


@pytest.mark.parametrize("changes", [
    {"until": float("inf")}, {"until": float("nan")}, {"until": time.time() + 10000},
    {"magnitude": True}, {"magnitude": 101}, {"kind": "execute-shell"},
    {"extra": "not accepted"}, {"kind": "memory-pressure", "magnitude": 65},
])
def test_invalid_control_cannot_enable_action(control: Path, changes: dict[str, object]) -> None:
    write(control, **changes)
    assert hooks.read_fault() is None


def test_file_type_and_size_limits(control: Path, tmp_path: Path) -> None:
    target = tmp_path / "target"
    write(target)
    control.symlink_to(target)
    assert hooks.read_fault() is None
    control.unlink()
    os.mkfifo(control)
    assert hooks.read_fault() is None
    control.unlink()
    control.write_text("x" * 1025)
    assert hooks.read_fault() is None


def test_delay_is_real_request_latency(control: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AEGIS_SHOP_FAULTS_ENABLED", "true")
    write(control, kind="network-latency", magnitude=50)
    client = TestClient(app())
    start = time.monotonic()
    assert client.get("/products").status_code == 200
    assert time.monotonic() - start >= 0.045
