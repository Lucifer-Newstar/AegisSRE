"""Bounded background orchestration, separate from HTTP request handling."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from eventbus import EventBus
from pydantic import ValidationError

from incidents_service.collectors import Collector
from incidents_service.delivery import RETENTION, DeliveryWorker
from incidents_service.engine import DomainError, ReliabilityLoop
from incidents_service.models import now


class Runtime:
    def __init__(
        self, loop: ReliabilityLoop, bus: EventBus | None = None, collector: Collector | None = None
    ):
        self.loop = loop
        self.bus = bus or EventBus(loop.settings.redis_url, stream_ttls=RETENTION)
        self.delivery = DeliveryWorker(loop, self.bus)
        self.collector = collector or (
            Collector(loop.settings) if loop.settings.collector_enabled else None
        )
        self.last_collection = -float("inf")
        self.last_tick: datetime | None = None
        self.last_error: str | None = None
        self.last_counts: dict[str, Any] = {}
        self.collector_failures: dict[str, str] = {}

    def tick(self) -> None:
        # Stage to PostgreSQL even when Redis is unavailable. A failed publish
        # leaves these rows intact; the next successful tick delivers them.
        if (
            self.collector
            and time.monotonic() - self.last_collection >= self.loop.settings.poll_seconds
        ):
            events = self.collector.collect()
            self.collector_failures = dict(self.collector.failures)
            for event in events:
                try:
                    self.delivery.stage(event)
                except (ValidationError, DomainError) as exc:
                    self.collector_failures[f"input:{event.type}"] = type(exc).__name__
            self.last_collection = time.monotonic()
        self.last_counts = self.delivery.tick()
        # Missing source evidence blocks autonomous work, not just readiness.
        self.last_counts["automatic_actions"] = (
            self.loop.run_automatic() if not self.collector_failures else 0
        )
        self.last_tick, self.last_error = now(), None

    def snapshot(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "delivery_consumer": self.delivery.consumer,
            "collector_enabled": self.collector is not None,
            "last_tick_at": self.last_tick.isoformat() if self.last_tick else None,
            "error": self.last_error,
            "collector_failures": self.collector_failures,
            "last_counts": self.last_counts,
        }

    def ready(self) -> bool:
        return bool(
            self.last_tick is not None
            and (now() - self.last_tick).total_seconds()
            <= max(60, self.loop.settings.poll_seconds * 2)
            and not self.last_error
            and not self.collector_failures
            and self.bus.ping()
        )

    def close(self) -> None:
        if self.collector:
            self.collector.close()
        self.bus.close()
