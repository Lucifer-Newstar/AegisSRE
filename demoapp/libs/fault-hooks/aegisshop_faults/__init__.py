"""Opt-in demo fault hooks with no HTTP control routes or command execution.

A local runner writes one bounded JSON file inside its owned demo workload.
Ordinary platform services never import this package. Fault labels/times stay
in the runner's private ground-truth journal, not in user-facing telemetry.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import stat
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Request
from starlette.responses import JSONResponse, Response

CONTROL_PATH = Path("/tmp/aegisshop-fault.json")
FAULTS = {"http-5xx", "network-latency", "cpu-saturation", "memory-pressure", "memory-exhaustion"}
EXCLUDED = {"/health", "/ready", "/metrics", "/faults", "/openapi.json", "/docs", "/redoc"}


@dataclass(frozen=True)
class Fault:
    kind: Literal["http-5xx", "network-latency", "cpu-saturation", "memory-pressure", "memory-exhaustion"]
    until: float
    magnitude: int


def read_fault(clock: float | None = None) -> Fault | None:
    """Malformed control state fails closed, never turns into an arbitrary action."""
    point = time.time() if clock is None else clock
    try:
        fd = os.open(CONTROL_PATH, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 1024:
                return None
            document = json.loads(source.read(1025))
        if not isinstance(document, dict) or set(document) != {"kind", "until", "magnitude"}:
            return None
        kind, until, magnitude = document["kind"], document["until"], document["magnitude"]
        if kind not in FAULTS or type(until) not in (float, int) or type(magnitude) is not int:
            return None
        if not point < until <= point + 600:
            return None
        limits = {"http-5xx": 100, "network-latency": 3000,
                  "cpu-saturation": 1000, "memory-pressure": 64, "memory-exhaustion": 384}
        if not 1 <= magnitude <= limits[kind]:
            return None
        return Fault(kind, float(until), magnitude)
    except (OSError, ValueError, TypeError):
        return None


def burn_cpu(milliseconds: int) -> None:
    deadline = time.perf_counter() + milliseconds / 1000
    value = 1
    while time.perf_counter() < deadline:
        value = (value * 1664525 + 1013904223) % 4294967296


def configure_fault_hooks(application: FastAPI) -> None:
    """Disabled unless explicitly enabled at application assembly.

    No endpoint, request header, query or body can enable or configure faults.
    The process must be in the demo namespace/runtime selected by its runner.
    """
    enabled = os.environ.get("AEGIS_SHOP_FAULTS_ENABLED") == "true"
    if not enabled:
        return
    if application.middleware_stack is not None:
        raise RuntimeError("Configure fault hooks before application startup")

    previous_lifespan = application.router.lifespan_context

    @asynccontextmanager
    async def fault_lifespan(app: FastAPI) -> AsyncIterator[Any]:
        # PID namespace init ignores peer SIGKILL. An opt-in fixed signal
        # handler makes the process exit immediately with a distinct code,
        # without an HTTP API or arbitrary command. No SIGKILL/OOM is claimed.
        # Normal workloads install no handler.
        def crash(signum: int, frame: Any) -> None:
            os._exit(70)
        previous_signal = signal.signal(signal.SIGUSR1, crash)
        try:
            async with previous_lifespan(app) as state:
                yield state
        finally:
            signal.signal(signal.SIGUSR1, previous_signal)

    application.router.lifespan_context = fault_lifespan
    resource_slot = asyncio.Semaphore(1)

    @application.middleware("http")
    async def fault_hook(request: Request, call_next: Any) -> Response:
        fault = read_fault() if request.url.path not in EXCLUDED else None
        if fault is None:
            response: Response = await call_next(request)
            return response
        if fault.kind == "http-5xx":
            return JSONResponse({"detail": "service unavailable"}, status_code=503)
        if fault.kind == "network-latency":
            # Real request delay at the dependency's application boundary, not
            # kernel packet shaping. The runner must preserve this distinction.
            await asyncio.sleep(min(fault.magnitude / 1000, max(0, fault.until - time.time())))
        elif fault.kind == "cpu-saturation":
            async with resource_slot:
                await asyncio.to_thread(burn_cpu, fault.magnitude)
        elif fault.kind == "memory-exhaustion":
            # Only the runner's verified 256Mi cgroup fixture may enable this.
            # Touch every page in the application process. Real OOM/restart
            # must be independently observed, never inferred from allocation.
            async with resource_slot:
                pages = bytearray(fault.magnitude * 1024 * 1024)
                for offset in range(0, len(pages), 4096):
                    pages[offset] = 1
                await asyncio.sleep(min(0.5, max(0, fault.until - time.time())))
                del pages
        elif fault.kind == "memory-pressure":
            # Bounded allocation, not memory-exhaustion/OOM acceptance. A
            # separate resource-limited experiment must prove an actual OOM.
            async with resource_slot:
                buffer = bytearray(fault.magnitude * 1024 * 1024)
                for offset in range(0, len(buffer), 4096):
                    buffer[offset] = 1
                await asyncio.sleep(min(0.5, max(0, fault.until - time.time())))
                del buffer
        result: Response = await call_next(request)
        return result
