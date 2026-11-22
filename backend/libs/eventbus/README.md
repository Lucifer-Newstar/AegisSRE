# Event transport

`EventBus` carries validated telemetry envelopes on canonical `st:<type>` Redis
Streams. Consumer groups start at the beginning of retained history. Consumers
must commit their database work before calling `ack`, and must deduplicate using
`envelope.id`. Redis stream ids are delivery ids, not domain-event ids.

## Retention

`stream_ttls` uses **seconds**, not a maximum message count. Trimming uses Redis's
own clock and `XTRIM MINID`. For example, `{"st:metric": 3600}` retains roughly one
hour of delivery history. Call `trim_all()` in worker housekeeping to trim idle
streams too. Without housekeeping, an idle stream is trimmed on its next publish.

Business events must already be durable in PostgreSQL before publishing. Do not
use a short stream retention as the only store for incidents, remediation or
audit. A stream is a delivery mechanism, not the evidence archive.

## Crash recovery

`read()` retrieves new messages. It does not pretend pending messages vanished
after a process crash. Workers also call `reclaim()` to transfer sufficiently idle
pending entries to a replacement consumer. The returned cursor supports bounded
pagination through pending work. Only acknowledge after the transaction commits.
A crash after commit but before acknowledgement is an expected duplicate.

Read bounds are explicit: 1..500 messages and at most five seconds of blocking.
`block_ms=0` is a nonblocking read, not Redis's wait-forever interpretation.
Connection and socket timeouts are bounded.

## Invalid events

By default, malformed messages raise an error and remain pending. A worker can
provide an `on_invalid` callback and explicitly call `quarantine()`. Quarantine
atomically writes a bounded diagnostic record to `dlq:<type>` and acknowledges
only the affected consumer group. It does not acknowledge healthy peer messages
or other groups. The dead-letter stream retains at most 1,000 records and needs
operator inspection; it is not a new domain-event type.

Raw telemetry can contain private application data. Dead-letter records stay in
the same internal Redis instance and should not be copied into public logs.

## Verification

Unit tests use fakeredis for delivery, reclamation, poison-message handling and
clock-based retention. Hosted CI additionally runs the same transport against a
fresh actual Redis 7 service. The real-server test refuses any nonlocal URL,
anything other than database 15, or a database containing existing data. It never
silently clears a database to make a test pass.

Transport primitives alone do not prove the full ingestion worker is connected.
That integration remains explicit in the platform acceptance ledger.
