"""Redis Streams transport with real time retention and crash recovery.

Business consumers remain idempotent on envelope.id. Acknowledgement is the
consumer's responsibility after its database transaction commits. Pending
messages can be reclaimed by another process after a crash. Malformed events
can be quarantined explicitly, never silently acknowledged or discarded.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from redis import Redis
from redis.exceptions import ResponseError
from telemetry import EventEnvelope
from telemetry.envelope import EVENT_TYPES

InvalidHandler = Callable[[str, str], None]


def stream_name(event_type: str) -> str:
    if event_type not in EVENT_TYPES:
        raise ValueError("Unknown event type")
    return f"st:{event_type}"


def _string(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, str):
        return value
    raise ValueError("Expected a Redis string")


class EventBus:
    def __init__(self, redis_url: str, stream_ttls: dict[str, int] | None = None) -> None:
        self._redis = Redis.from_url(
            redis_url, decode_responses=True, socket_connect_timeout=3, socket_timeout=10
        )
        self._stream_ttls = stream_ttls or {}
        valid = {stream_name(kind) for kind in EVENT_TYPES}
        if any(
            key not in valid or type(ttl) is not int or ttl <= 0
            for key, ttl in self._stream_ttls.items()
        ):
            raise ValueError("Retention requires known st:<type> keys and positive seconds")

    def publish(self, envelope: EventEnvelope) -> str:
        stream = stream_name(envelope.type)
        message_id = self._redis.xadd(stream, {"envelope": envelope.model_dump_json()})
        self._trim(stream)
        return _string(message_id)

    def _trim(self, stream: str) -> None:
        seconds = self._stream_ttls.get(stream)
        if seconds:
            server_seconds, microseconds = self._redis.time()
            cutoff_ms = max(0, (int(server_seconds) - seconds) * 1000 + int(microseconds) // 1000)
            self._redis.xtrim(stream, minid=f"{cutoff_ms}-0", approximate=False)

    def trim_all(self) -> None:
        """Housekeeping also trims streams that have gone idle."""
        for stream in self._stream_ttls:
            if self._redis.exists(stream):
                self._trim(stream)

    def ensure_group(self, event_type: str, group: str) -> None:
        try:
            self._redis.xgroup_create(stream_name(event_type), group, id="0", mkstream=True)
        except ResponseError as exc:
            # Redis uses BUSYGROUP; some compatible test servers use BUSGROUP.
            if not any(code in str(exc) for code in ("BUSYGROUP", "BUSGROUP")):
                raise

    def _entries(
        self, entries: Any, on_invalid: InvalidHandler | None
    ) -> list[tuple[str, EventEnvelope]]:
        messages: list[tuple[str, EventEnvelope]] = []
        for message_id, fields in entries:
            mid = _string(message_id)
            try:
                raw = fields.get("envelope", fields.get(b"envelope"))
                envelope = EventEnvelope.model_validate_json(_string(raw))
            except (ValueError, TypeError, UnicodeError) as exc:
                if on_invalid is None:
                    raise ValueError(
                        f"Invalid envelope in message {mid}; message remains pending"
                    ) from exc
                on_invalid(mid, type(exc).__name__)
                continue
            messages.append((mid, envelope))
        return messages

    def read(
        self,
        event_type: str,
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 1000,
        on_invalid: InvalidHandler | None = None,
    ) -> list[tuple[str, EventEnvelope]]:
        if not 1 <= count <= 500 or not 0 <= block_ms <= 5000:
            raise ValueError("Read count must be 1..500 and block_ms 0..5000")
        self.ensure_group(event_type, group)
        options: dict[str, Any] = {"count": count}
        if block_ms:
            options["block"] = block_ms
        raw = self._redis.xreadgroup(group, consumer, {stream_name(event_type): ">"}, **options)
        messages: list[tuple[str, EventEnvelope]] = []
        for item in raw or []:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise ValueError("Unexpected Redis stream response")
            _stream, entries = item
            messages.extend(self._entries(entries, on_invalid))
        return messages

    def reclaim(
        self,
        event_type: str,
        group: str,
        consumer: str,
        *,
        min_idle_ms: int = 30000,
        count: int = 100,
        cursor: str = "0-0",
        on_invalid: InvalidHandler | None = None,
    ) -> tuple[str, list[tuple[str, EventEnvelope]]]:
        if min_idle_ms < 0 or not 1 <= count <= 500:
            raise ValueError("Invalid reclaim bounds")
        self.ensure_group(event_type, group)
        raw = self._redis.xautoclaim(
            stream_name(event_type), group, consumer, min_idle_ms, start_id=cursor, count=count
        )
        return _string(raw[0]), self._entries(raw[1], on_invalid)

    def quarantine(self, event_type: str, group: str, message_id: str, reason: str) -> None:
        """Atomically retain a bounded invalid-event record and ack this group only."""
        stream = stream_name(event_type)
        entries = self._redis.xrange(stream, min=message_id, max=message_id, count=1)
        original = json.dumps(entries[0][1], default=str)[:16000] if entries else "{}"
        with self._redis.pipeline(transaction=True) as pipeline:
            pipeline.xadd(
                f"dlq:{event_type}",
                {"source_id": message_id, "reason": reason[:120], "original": original},
                maxlen=1000,
                approximate=False,
            )
            pipeline.xack(stream, group, message_id)
            pipeline.execute()

    def ack(self, event_type: str, group: str, message_id: str) -> None:
        self._redis.xack(stream_name(event_type), group, message_id)

    def stream_length(self, event_type: str) -> int:
        return int(self._redis.xlen(stream_name(event_type)))

    def pending_count(self, event_type: str, group: str) -> int:
        stream = stream_name(event_type)
        if not self._redis.exists(stream):
            return 0
        info = self._redis.xpending(stream, group)
        return int(info.get("pending", 0)) if info else 0

    def ping(self) -> bool:
        return bool(self._redis.ping())

    def close(self) -> None:
        self._redis.close()
