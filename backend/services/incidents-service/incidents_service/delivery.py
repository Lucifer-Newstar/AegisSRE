"""At-least-once transport around the transactional reliability loop.

PostgreSQL is the source of business durability. Redis acknowledgements happen
only after ingest commits. Publishing can repeat after a crash; envelope IDs
remain unchanged. Multiple dispatchers are safe, but may publish duplicates.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC
from typing import Any

from eventbus import EventBus
from pydantic import ValidationError
from telemetry import EventEnvelope

from incidents_service.engine import DomainError, ReliabilityLoop

logger = logging.getLogger(__name__)
INPUT_TYPES = ("deployment", "log", "trace", "k8s_event", "metric", "health")
RETENTION = {
    "st:metric": 3600,
    "st:health": 3600,
    "st:log": 86400,
    "st:trace": 86400,
    "st:k8s_event": 86400,
    "st:anomaly": 604800,
    "st:deployment": 2592000,
    "st:incident": 2592000,
    "st:remediation": 2592000,
    "st:audit": 2592000,
}


class DeliveryWorker:
    def __init__(
        self,
        loop: ReliabilityLoop,
        bus: EventBus,
        *,
        group: str = "reliability-v1",
        consumer: str | None = None,
        batch_size: int = 100,
        reclaim_idle_ms: int = 30000,
    ):
        if not 1 <= batch_size <= 500 or reclaim_idle_ms < 0:
            raise ValueError("Invalid worker bounds")
        self.loop, self.bus = loop, bus
        self.group, self.consumer = group, consumer or f"worker-{uuid.uuid4().hex}"
        self.batch_size, self.reclaim_idle_ms = batch_size, reclaim_idle_ms
        self.cursors = dict.fromkeys(INPUT_TYPES, "0-0")

    def stage(self, event: EventEnvelope) -> None:
        """Durably queue a collector event before attempting network delivery."""
        from incidents_service.models import Event

        validated = Event.model_validate(event.model_dump(mode="json"))
        if validated.type not in INPUT_TYPES:
            raise ValueError("Only input telemetry may be staged")
        validated.timestamp = validated.timestamp.astimezone(UTC)
        document = validated.model_dump(mode="json")
        with self.loop.repo.transaction() as tx:
            previous = tx.event(validated.id) or tx.queued_event(validated.id)
            if previous is not None and previous != document:
                raise DomainError("Collector event id reused with different content")
            if previous is None:
                tx.emit(document)

    def dispatch(self) -> int:
        with self.loop.repo.transaction() as tx:
            pending = tx.pending(self.batch_size)
        delivered = 0
        for seq, document in pending:
            # An invalid outbox item is a programming/storage fault. Leave it
            # durable and fail visibly instead of silently deleting evidence.
            self.bus.publish(EventEnvelope.model_validate(document))
            with self.loop.repo.transaction() as tx:
                tx.delivered(seq)
            delivered += 1
        return delivered

    def _consume(self, kind: str, message_id: str, envelope: EventEnvelope) -> None:
        from incidents_service.models import Event

        try:
            if envelope.type != kind:
                raise ValueError("Envelope does not match its input stream")
            event = Event.model_validate(envelope.model_dump(mode="json"))
        except (ValidationError, ValueError) as exc:
            self._quarantine(kind, message_id, exc)
            return
        try:
            self.loop.ingest(event)
        except DomainError as exc:
            self._quarantine(kind, message_id, exc)
            return
        # Storage/network/runtime errors leave the message pending, including
        # unexpected ValueError failures inside the detector/reasoner.
        self.bus.ack(kind, self.group, message_id)

    def _quarantine(self, kind: str, message_id: str, exc: Exception) -> None:
        self.bus.quarantine(kind, self.group, message_id, type(exc).__name__)
        logger.warning("Quarantined %s message %s (%s)", kind, message_id, type(exc).__name__)

    def consume(self) -> int:
        processed = 0
        for kind in INPUT_TYPES:

            def invalid(mid: str, reason: str, event_type: str = kind) -> None:
                self.bus.quarantine(event_type, self.group, mid, reason)

            cursor, reclaimed = self.bus.reclaim(
                kind,
                self.group,
                self.consumer,
                min_idle_ms=self.reclaim_idle_ms,
                count=self.batch_size,
                cursor=self.cursors[kind],
                on_invalid=invalid,
            )
            self.cursors[kind] = cursor
            fresh = self.bus.read(
                kind,
                self.group,
                self.consumer,
                count=self.batch_size,
                block_ms=0,
                on_invalid=invalid,
            )
            for mid, envelope in [*reclaimed, *fresh]:
                self._consume(kind, mid, envelope)
                processed += 1
        return processed

    def tick(self) -> dict[str, Any]:
        sent = self.dispatch()
        consumed = self.consume()
        self.loop.sweep()
        sent += self.dispatch()
        self.bus.trim_all()
        return {"published": sent, "consumed": consumed}
