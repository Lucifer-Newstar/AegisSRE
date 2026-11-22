# Observed deployment windows

The reliability runtime owns observed rollout state in PostgreSQL. SQLite is the
explicit local/unit-test backend. These observations are not deployment risk
predictions, causal attribution or permission to execute a rollback.

## Producers and identity

Post the v0.2 deployment envelope to the protected metadata API. Each lifecycle
event has its own immutable envelope `id`. Put a stable `deployment_id` in the
payload to group an in-progress event and its terminal event into one logical
deploy. The identity is scoped by service and environment. Reusing a revision
never proves that two events are the same deployment.

`started_at` is the aware producer start for the whole rollout, not the timestamp
of each phase. It cannot follow the event timestamp. An identity cannot change
revision, a known previous revision or its start, or flip a terminal phase. A
previous revision may be filled once. A matching explicit start may confirm an
initially implicit start. Old producers remain readable, but missing logical
identity is excluded from a reliable logical-deployment denominator. Existing
raw deployment events not indexed into rollout state are counted as unknown.

## Observations and timing

The observation window is 180 seconds from the producer start, or from the first
event when the start is absent. Producer-reported failure or baseline-qualified
latency, error or SLO-burn anomalies can mark it bad. Aggregate and revision-only
series are supported. Instance/canary-labelled series are not silently combined
with an aggregate baseline. Overlapping windows remain ambiguous.

A bad observation emits one durable `rollout.bad` event and audit entry in the
same transaction as its state. Outbox transport is at least once, so downstream
consumers still deduplicate the event ID. The event explicitly denies causal
proof and execution authority. The policy/approval/execution boundary is intact.
`flagged_at` is the actual decision clock; `bad_observed_at` is the source clock.
Flag latency is null without a producer start or with inconsistent clock order.
A low source timestamp does not establish a fast real-time detector.

After the window and 15 seconds of arrival allowance, observed healthy needs a
succeeded phase, explicit start, no ambiguity, three baseline-qualified normal
samples each for latency and error, and healthy SLO/error/latency health. Last
metric and health observations must lie in the final 45 seconds. Missing evidence
ends as insufficient, never healthy. Late in-window evidence reopens the result
for evaluation, rather than preserving stale health. Expired windows are selected
in SQL so newer active windows cannot permanently crowd out finalization.

## Read APIs and honest counting

Through the authenticated gateway:

- `GET /api/v1/deployment-intelligence/rollouts?service=catalog-service`
- `GET /api/v1/deployment-intelligence/summary?service=catalog-service`

Direct paths omit `/api/v1`. Reads are limited to configured allowed services and
the runtime environment. `since` defaults to the previous 30 days and must be an
aware time within the previous 90 days. The rollout list is bounded and reports
truncation. Counts use SQL aggregates, not that bounded list.

Change failure rate is null when there are unidentified/unmapped events, unknown
outcomes or no logical-deployment denominator. A separate observed-finalized
rate, coverage and bounds describe the identified cohort. Metric-associated bad
or healthy outcomes from ambiguous windows remain unknown for CFR; an explicit
producer failure is still a known failure. These are observed platform outcomes,
not independently labelled evaluation ground truth.

## Proof boundary

Unit tests cover identity, conflicts, overlap, conservative finalization, late
evidence, unknown denominators and SQLite reopen. The hosted storage gate uses
actual PostgreSQL for grouping, time-window counts, deduplication and reopen.
The runtime gate posts clearly labelled synthetic CI inputs through the actual
metadata API, waits for collection, reads through the real gateway, restarts the
application and verifies SQL state plus actual Redis publication.

Those gates do not prove a real workload fault, under-three-minute detection,
canary safety, risk calibration or the ten-fault acceptance targets. Those remain
separate work in the acceptance ledger.
