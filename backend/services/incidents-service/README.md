# Incidents and reliability core

Milestone 1 implementation, not the finished platform. See the
[acceptance ledger](../../../docs/implementation/status.md).

## Run the real API locally

Python 3.12 or newer:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r backend/services/incidents-service/requirements.lock
pip install --no-deps -e backend/services/incidents-service
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
| `GET /ready` / `GET /metrics` | Database readiness and API counters |

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
- a configured target allowlist (JSON in `AEGIS_ALLOWED_TARGETS`);
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

## Tests

```bash
pytest backend/services/incidents-service
ruff check backend/services/incidents-service
mypy backend/services/incidents-service
```

The checked-in lock contains the dependency versions used for this milestone.
Unit tests use isolated SQLite databases and mock subprocess calls. They do not
claim a real PostgreSQL, Kubernetes or full Compose acceptance test.
