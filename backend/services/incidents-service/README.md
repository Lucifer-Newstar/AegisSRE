# Incidents and reliability core

Milestone 1 implementation, not the finished platform. See the
[acceptance ledger](../../../docs/implementation/status.md).

## Run the real API locally

Python 3.12 or newer:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r backend/services/incidents-service/requirements-runtime.lock
pip install --no-deps -e backend/libs/telemetry -e backend/libs/eventbus \
  -e backend/services/incidents-service
AEGIS_DEV_MODE=true python -m uvicorn incidents_service.main:create_app \
  --factory --host 127.0.0.1 --port 8201
```

This explicitly selects unauthenticated **local simulation**. Do not expose it
on a network. For authenticated use, set `AEGIS_API_TOKEN` in the process
environment and leave `AEGIS_DEV_MODE` false. Never put a token into a committed
file or a browser URL. OpenAPI is available at `/docs` on the running API.
`incidents_service.contract` is a schema-check fixture, not a server entrypoint.

SQLite persists to `aegis-incidents.db` by default. For PostgreSQL, set
`AEGIS_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DB` through a secret
manager or local environment file. Schema creation is additive in this first
milestone. Existing data is never dropped on startup. SQLite is supported with
one worker; use PostgreSQL for multiple processes. The database principal must
be able to create the `aegis_*` tables on first startup.

## API

All endpoints other than `/health` need `Authorization: Bearer <token>` outside
explicit local dev mode.

| Endpoint | Purpose |
|---|---|
| `POST /events` | Ingest one validated v0.2 telemetry envelope |
| `GET /events?service=...&environment=...&event_type=...` | Inspect bounded evidence history |
| `GET /events/{id}` | Retrieve cited evidence |
| `GET /incidents` / `GET /incidents/{id}` | Incidents, signals, reasoning, plan, timeline |
| `POST /incidents/{id}/approve` / `reject` / `defer` | Decision body: actor and optional note |
| `POST /actions/{id}/execute` | Attempt an approved or eligible policy-authorized action |
| `GET /postmortems` / `GET /postmortems/{id}` | Postmortems after verified closure only |
| `GET /audit?incident_id=...` | Append-only audit records |
| `GET /autonomy` / `POST /autonomy` | Policy view; set observe/recommend/auto-safe |
| `GET /ready` / `GET /metrics` | Dependency/worker readiness and API counters |
| `GET /runtime` | Worker progress, collection failures and delivery counts |

A bearer token identifies a single operator/integration principal. The `actor`
field is an asserted audit label, not independent identity verification or a
multi-user RBAC system.

A denied execution has `execution_output` beginning with `DENIED:` and leaves
the incident unchanged. It is recorded in the audit store. A successful
simulation explicitly says `SIMULATION ONLY` and still requires independent
recovery telemetry. No endpoint lets a caller directly set an incident to closed.

## Detection and recovery semantics

- The first 12 normal samples warm up each distinct service/environment/metric/
  unit/label series. Collectors should supply rates and gauges, not raw counters.
- A robust statistical distance and Isolation Forest score are both recorded.
  Constant baselines use an explicit noise floor; Isolation Forest alone cannot
  separate every point from a completely constant training set.
- Increasing producer timestamps are required per metric series. Repeating an
  identical event id/content is safe; reusing an id for different content is not.
- Affected series need at least three healthy samples after execution. Health,
  error-rate, latency and SLO checks must also all be fresh and passing.
- Missing telemetry cannot establish recovery. Expired verification escalates.
- Postmortem `mttd_seconds` is unknown unless a fault-onset record exists.
  Detection event lag is reported separately and is not silently called MTTD.

The deterministic reasoner ranks known symptoms and recent deployment timing.
It is not an LLM and its confidence is not a calibrated probability. It retains
citations and states that correlation is not proof of causation.

## Execution boundaries

Simulation is the default. Kubernetes execution additionally requires:

- `AEGIS_EXECUTOR=kubernetes`, a bearer token, dev mode off, explicit
  `AEGIS_KUBE_CONTEXT` and namespace;
- a configured target allowlist (JSON in `AEGIS_ALLOWED_TARGETS`) and incident
  environment matching `AEGIS_ENVIRONMENT`;
- a deployment labelled `aegissre.managed=true` in that exact namespace;
- a policy/approval decision, rate limits and cooldown checks;
- at least two replicas for a rolling restart; one-step bounded scale changes;
- numeric Kubernetes rollout revisions for rollback, with distance one or two.
  A git SHA or image tag is **not** a Kubernetes rollout revision.

Commands are fixed argv lists, never a shell or LLM-provided executable text.
Config updates and instance replacement are forbidden by the initial policy and
have no generic executor. They are not silently mapped to destructive actions.
Auto execution is not scheduled in milestone 1. Its gates default closed when
required context is missing. No real cluster action has been verified yet.

`observe` blocks new actions, including approved actions. An action already
submitted to Kubernetes cannot be retroactively prevented by a flag change.
Interrupted/uncertain executions escalate and are never automatically retried.

## Live collection and delivery

The optional background runtime now collects fixed Prometheus queries, registry
readiness/SLO metadata and deployment history. Enable `AEGIS_WORKER_ENABLED` with
`AEGIS_REDIS_URL`; enable `AEGIS_COLLECTOR_ENABLED` with all three configured
origins: `AEGIS_PROMETHEUS_URL`, `AEGIS_REGISTRY_URL`, `AEGIS_DEPLOYMENTS_URL`.
The default collection interval is 15 seconds. Redis delivery is checked each
worker cycle. HTTP requests are not blocked by collection.

`docker compose up --build incidents-service catalog-service` starts this loop
against actual PostgreSQL, Redis and Prometheus. Supply `AEGIS_API_TOKEN` through
your local environment or secret manager first. The default fails closed if it
is absent; Compose does not enable unauthenticated dev mode. All published local
stack ports bind to loopback. The executor remains simulation-only in Compose.

Inputs are staged in the PostgreSQL outbox before Redis publication. Consumers
ACK only after the ingest transaction commits. A crash between publish/delete
or commit/ACK can repeat a delivery, but stable event IDs prevent duplicate
business effects. Pending messages are reclaimed after 30 seconds. Invalid,
conflicting or out-of-order entries go to bounded `dlq:<type>` streams; unexpected
database/runtime failures remain pending. Inspect DLQs instead of hiding them.

Metrics are rates/gauges, scoped by service and environment, with stale and
non-finite results excluded. CPU is percent of one process core, not percent of
a container's CPU quota. Recovery needs traffic, fresh readiness and passing
error/latency measurements. Its one-minute SLI check does not claim a 30-day SLO
or known remaining error budget. Missing series and zero traffic never prove
recovery. Loki/Tempo read-only evidence tools and trace joins remain later work.

The current embedded runtime uses one API process per deployment. PostgreSQL
serializes business transactions and separate dispatchers can repeat safe
at-least-once delivery, but multi-replica execution ownership is not yet a
supported deployment mode. Do not start multiple API replicas against an active
executor. An operator restart escalates interrupted actions for reconciliation.

## Tests

Install the root `requirements-dev.txt` before running the complete tests. The
process-metric checks exercise all four demo packages too.

```bash
pytest backend/services/incidents-service
ruff check backend/services/incidents-service
mypy backend/libs/telemetry backend/libs/eventbus backend/services/incidents-service
```

Unit tests use isolated SQLite and in-memory Redis, with injected failure paths.
CI separately runs actual PostgreSQL/Redis and Compose collection/restart checks
through `scripts/check_runtime_stack.py`. Its controlled telemetry fixtures prove
wiring, not real fault recovery, detection accuracy, RCA accuracy or the full
acceptance targets. No real Kubernetes action has been verified yet.

`requirements.lock` pins external development dependencies. The runtime-only
subset is in `requirements-runtime.lock`; local telemetry/eventbus packages are
installed from this repository, never fetched as unrelated packages from PyPI.
