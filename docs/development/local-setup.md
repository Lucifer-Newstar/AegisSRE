# Local development setup

The [implementation ledger](../implementation/status.md) distinguishes implemented
code, live integration and acceptance results. The existing design documents are
targets, not a claim that every phase is complete.

## Prerequisites

- Python 3.12 or newer, Git, and a shell.
- Docker with Compose v2 for the full local stack.
- Node.js 22 for the Next.js console.
- `kubectl` and kind only for the Kubernetes milestone.

Use WSL2 on Windows for the shell commands below. Work from the repository root.

## Python environment

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest
ruff check backend demoapp
mypy backend demoapp
python scripts/check_contract_drift.py
python scripts/validate_yaml.py
```

`requirements-dev.txt` is the complete editable-package list used by CI. It uses
the reliability package's checked-in dependency constraints. Tests force the
catalogue/deployment stores into isolated in-memory databases; reset helpers must
never run against a user's runtime database. Real PostgreSQL tests are separate,
using `AEGIS_TEST_DATABASE_URL` and an isolated test database.

## Compose

```bash
cp .env.example .env
make infra-up
```

The example credentials are **development fixtures**, not suitable for a network
or production installation. The catalogue and deployment APIs bind to host
loopback. Other existing stack ports are still development ports; do not expose
this stack to an untrusted network. An authenticated gateway and further network
hardening belong to the remaining runtime integration.

`PLATFORM_DATABASE_URL` must match `POSTGRES_USER`, `POSTGRES_PASSWORD` and
`POSTGRES_DB`. URL-encode special characters in URL credentials. Compose passes
this URL as `DATABASE_URL` to the registry and deployment services. Those services
persist metadata to PostgreSQL. Do not commit `.env` or any real credentials.

| Service | Local address |
|---|---|
| Console | http://localhost:3030 |
| Grafana | http://localhost:3000 |
| Prometheus | http://localhost:9090 |
| Registry | http://localhost:8101/services |
| Deployment history | http://localhost:8701/deployments |
| Catalog app | http://localhost:9001/products |
| Loki | http://localhost:3100 |
| Tempo | http://localhost:3200 |

The reliability-core API can currently be run separately using its
[README](../../backend/services/incidents-service/README.md). Its Compose/collector
integration is a subsequent milestone; a mock incident list in the existing
console is not proof of that integration.

### Metadata persistence check

On an isolated development stack only, this command creates controlled fixture
records and deletes the seeded cart entry:

```bash
python scripts/check_metadata_stack.py --seed
docker compose restart registry-service deployments-service
python scripts/check_metadata_stack.py --verify
```

This exact restart check also runs in hosted CI. It tests the real APIs and
PostgreSQL, not an in-process mock. The fixture script is not for a production
catalogue.

### Preserve or remove data deliberately

```bash
docker compose stop                 # stop, keep containers and volumes
docker compose down                 # remove containers, keep named volumes
make infra-down                     # removes named volumes too: DESTRUCTIVE reset
```

Use a backup before changing persistent data. A Docker rebuild does not require
deleting the database. Do not use a volume reset as the first troubleshooting
step.

## Native service development

Outside Compose, the metadata services use ignored local SQLite files by default:
`aegis-registry.db` and `aegis-deployments.db`. Set `DATABASE_URL` to an explicit
SQLite file or a PostgreSQL URL to select another database. The services do not
read the Compose `.env` file themselves.

Registry probing is enabled with `REGISTRY_PROBE=true`. Registered probe URLs must
have a host in `REGISTRY_ALLOWED_HOSTS` (a JSON array of allowed service DNS names).
Credentials in probe URLs and redirects are rejected. With probing enabled,
readiness refresh runs on a 15-second cadence. Registration alone does not prove
a service is healthy.

The deployment service starts with no fabricated history. `DEPLOYMENT_REVISION`
can record the deployment service's own explicitly supplied running revision;
other deployments must arrive through the API or a real deployment hook.
Producer timestamps, not receive time, determine the latest deployment.

## Frontend

```bash
cd frontend
npm ci
npm run dev
```

The console uses `REGISTRY_URL` and `DEPLOYMENTS_URL` for server-side reads.
Unconfigured or unreachable APIs in the existing scaffold still show labelled
mock fallback. Live intelligence and the remaining pages are tracked in the
acceptance ledger.

## Kubernetes

The registry and deployment manifests now read `DATABASE_URL` from the
`aegissre-database` Secret, key `url`, in their namespace. Create that Secret
through the target environment's secret workflow before applying the workloads.
No real credentials are committed. The complete kind dependency/bootstrap path
is still a remaining acceptance item. See [Kubernetes notes](../../infra/k8s/README.md).

## Troubleshooting

- Check `docker compose ps -a` and service logs before changing configuration.
- If readiness is 503, check the configured database, not a fabricated green
  dependency response.
- If a probe is unhealthy, verify the registered URL, allowlist, service DNS and
  that service's `/ready` response.
- If imports fail, activate the virtual environment and reinstall
  `requirements-dev.txt`; the new storage library is a local package.
- For manual image builds of demo and metadata services, use the repository root
  as context, for example `docker build -f demoapp/aegisshop/catalog-service/Dockerfile .`
  or `docker build -f backend/services/registry-service/Dockerfile .`.
- The shared telemetry library's `observability` extra owns each application's
  OTLP providers and request-context log handler. Configure instrumentation before
  startup. A blank OTLP endpoint disables exports without changing global providers.
- Loki queries use `service_name` and `deployment_environment` labels. Logs include
  `trace_id` in their JSON bodies when emitted in a request; collected events retain
  it as a top-level envelope field. Collector failures are visible at `/runtime`.
- `python3 scripts/check_observability_stack.py` checks actual OTLP, Loki, Tempo,
  Redis and SQL delivery on a running disposable stack. It is not an RCA benchmark.
