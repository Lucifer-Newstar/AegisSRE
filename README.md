# AegisSRE

**AI-Powered Autonomous Site Reliability & Deployment Intelligence Platform**

*Intelligent monitoring · Deployment risk intelligence · Incident detection · Root-cause analysis · Controlled autonomous remediation*

A personal project by **Navin Jairam** ([@Lucifer-Newstar](https://github.com/Lucifer-Newstar)).

![Status](https://img.shields.io/badge/status-foundation--phase-0f766e) ![CI](https://img.shields.io/badge/CI-github--actions-blue)

AegisSRE observes a deployed cloud-native application, analyzes its telemetry, detects
abnormal behavior, identifies and correlates incidents, determines probable root causes,
recommends evidence-backed remediation actions, and verifies system recovery — while
keeping humans in control of higher-risk operations.

> **Observe everything. Trust evidence. Reason over context. Act within boundaries. Verify the result.**
>
> The objective is not to replace the SRE. It is to allow the SRE to move from reactive
> firefighting toward intelligent, evidence-driven, and increasingly autonomous reliability
> engineering.

---

## 1. Project Status (honest: built vs designed)

This repo is under active implementation. The design documents cover the full
vision; the acceptance ledger separates implemented code from measured results.

Implementation is continuing against the complete approved scope. See the
[feature-by-feature acceptance ledger](docs/implementation/status.md) for code,
measured checks and remaining work. Code presence is not an acceptance result.

**Implemented:**

- Local observability configurations: OpenTelemetry Collector, Prometheus,
  Grafana, Loki, Tempo, Postgres and Redis. CI checks selected running stacks;
  full-platform acceptance remains in the ledger.
- Shared backend libraries: telemetry envelope contract (`backend/libs/telemetry`) and a
  Redis Streams event bus (`backend/libs/eventbus`), both tested.
- FastAPI service template (`backend/services/_template`) used as the copy-paste pattern
  for every service.
- **registry-service** — service catalogue + health aggregation API (:8101, live).
- **deployments-service** — DI-1 deployment history API (:8701, live).
- **Reliability API and background runtime** (`backend/services/incidents-service`, :8201):
  live scoped metric/health/deployment collection, durable Redis processing and
  incident/audit outbox delivery, statistical + Isolation Forest detection, cited
  deterministic RCA, approvals, policy and recovery gates. The default executor
  is explicitly simulation; no real-cluster success is claimed.
- **API gateway** (`backend/services/api-gateway`, host :8080): fixed routes,
  bearer auth, Redis-backed rate limits and principal-bound audit writes. Console
  session/login and migration to this entrypoint remain in progress.
- **AegisShop** demo app: catalog (:9001), cart (:9002), order (:9003), payment (:9004)
  services with tests.
- **Console** (Next.js 14 on :3030): overview, services, deployments, and incidents
  pages — live data where APIs exist, clearly-marked mock fallback elsewhere.
- Initial application K8s manifests (Kustomize base) and Terraform skeleton (`iac/`).
  Full cluster bootstrap and parity with the expanded Compose stack remain open.
- CI: YAML/Compose validation, kubeconform + kustomize checks, docs link check, ruff,
  mypy (strict), pytest, contract-drift guard, image builds, actual PostgreSQL/Redis
  tests and Compose collection/restart gates.
- OpenAPI contract set with a CI drift guard, 14-diagram UML set, ADRs.

**Remaining scope** (see [docs/planning/](docs/planning/) and
[docs/architecture/](docs/architecture/)):

- Log/trace evidence tools, trace joins and measured anomaly/incident acceptance;
  LLM reasoning, pgvector RAG knowledge base and Ask Aegis assistant.
- Console approvals, scheduled safe autonomy, live executor verification and
  complete evaluation of the implemented policy/recovery core.
- Chaos lab (`chaoslab/` — planned), DI-2…DI-7 deployment-intelligence capabilities
  beyond DI-1 tracking.
- Full eight-page console scope, kind-cluster deployment, evaluation harness.

Nothing in this repo claims otherwise: design docs describe the target; the phase plan
tracks what is proven.

## 2. What the Platform Does (target design)

| Capability | Description |
|---|---|
| **Continuous Observability** | Collects metrics, logs, distributed traces, Kubernetes events, deployment history, and service health via OpenTelemetry, Prometheus, Loki, and Tempo. |
| **Anomaly Detection** | ML/statistical models (Isolation Forest + statistical baselines) detect latency spikes, error-rate increases, resource anomalies, and traffic shifts. |
| **Incident Management** | Correlates anomalies into incidents with severity, affected services, timestamps, telemetry evidence, deployment context, and status. |
| **Root-Cause Analysis** | An AI reasoning layer combines logs, metrics, traces, deployments, and runbooks to produce evidence-backed root-cause explanations. |
| **AI-Assisted Remediation** | Recommends actions: restart unhealthy workload, rollback deployment, scale service, replace instance, adjust configuration, or escalate. |
| **Deployment Intelligence** | Tracks every deployment; ML risk scoring, bad-rollout detection, change-incident correlation, policy-gated safe rollback, canary analysis, and change-failure analytics (DI-1…DI-7). |
| **Controlled Autonomy** | Low-risk, predefined, reversible actions execute automatically; high-risk operations require human approval. |
| **Recovery Verification** | Confirms health, error rates, latency, and SLOs recovered before closing the incident. |
| **Postmortems** | AI-generated incident postmortems with timeline, evidence, and measured MTTD/MTTR. |

Autonomy pipeline: **Detect → Investigate → Explain → Recommend → Approve/Execute → Verify**

## 3. High-Level Architecture

```text
                         USER
                          │
                          ▼
                ┌───────────────────┐
                │   Web Dashboard   │
                │   Next.js console │
                └─────────┬─────────┘
                          │
                     API Gateway
                          │
              ┌───────────┴───────────┐
              │                       │
              ▼                       ▼
       Platform Services        Incident Services
              │                       │
              └───────────┬───────────┘
                          │
                     Event Layer
                          │
       ┌──────────────────┼──────────────────┐
       │                  │                  │
       ▼                  ▼                  ▼
     CI/CD            Deployment       Observability
       │                  │          ┌───────┼───────┐
       │                  │          │       │       │
       │                  │        Logs   Metrics  Traces
       └──────────────────┼──────────┴───────┴───────┘
                          │
                 Intelligence Engine
                          │
              ┌───────────┴───────────┐
              │                       │
              ▼                       ▼
       ML Anomaly Detection       AI Reasoning
              │                       │
              │                ┌──────┴──────┐
              │                │             │
              │               RAG        Tool Access
              └────────────────┴─────────────┘
                               │
                               ▼
                       Incident Analysis
                               │
                               ▼
                     Remediation Planner
                               │
                         Policy Engine
                               │
                    ┌──────────┴──────────┐
                    │                     │
              Human Approval       Safe Autonomous
                    │                 Actions
                    └──────────┬──────────┘
                               │
                               ▼
                         Remediation
                               │
                               ▼
                     Recovery Verification
                               │
                               ▼
                         Incident Closed
```

## 4. Repository Layout

```
AegisSRE/
├── .github/workflows/    CI pipeline (GitHub Actions)
├── backend/              Platform services + shared libs (Python / FastAPI)
│   ├── libs/             telemetry envelope, Redis Streams eventbus
│   └── services/         _template, registry-service, deployments-service, incidents-service
├── demoapp/aegisshop/    AegisShop demo app (catalog, cart, order, payment)
├── docs/                 Documentation hub (index: docs/README.md)
│   ├── project/          Proposal & roadmap
│   ├── planning/         Features, product vision, phases, timeline, decision log
│   ├── contracts/        OpenAPI contracts + drift-guard manifest
│   ├── architecture/     System design, autonomy/telemetry models, UML set, ADRs
│   ├── development/      Conventions, local setup, tech stack
│   └── operations/       Evaluation methodology
├── frontend/             SRE console (Next.js / TypeScript)
├── iac/                  Infrastructure as Code (Terraform, skeleton)
├── infra/                Observability configs + Kubernetes manifests
│   ├── grafana/          Dashboards + provisioning
│   ├── k8s/              Kustomize base (1:1 with Compose, ADR-0005)
│   ├── loki/  otel/  prometheus/  tempo/
├── scripts/              Dev/CI utility scripts (YAML validation, contract drift)
├── docker-compose.yml    Local development stack (Compose now, K8s-ready)
└── Makefile              Common developer tasks
```

Planned top-level dirs in the design docs (`ml/`, `ai/`, `chaoslab/`) do not exist yet;
they land in phases P3–P7.

## 5. Quickstart (Local Development)

Prerequisites: Docker + Docker Compose v2. For running tests outside containers:
Python **3.12+** and Node.js 22.

```bash
# 1. Configure local credentials (preserve an existing .env)
test -f .env || cp .env.example .env
# Set AEGIS_API_TOKEN to a long random value in .env or your secret manager.
# No default API token is supplied. Without one the reliability service fails closed.

# 2. Bring up the local stack
make infra-up

# 3. Verify the stack
docker compose ps

# 4. Open the dashboards
#    Grafana       → http://localhost:3000   (admin / aegis)
#    Console       → http://localhost:3030
#    Prometheus    → http://localhost:9090
#    Loki          → http://localhost:3100
#    Tempo         → http://localhost:3200
#    Registry      → http://localhost:8101/services
#    Deployments   → http://localhost:8701/deployments
#    Incidents API → http://localhost:8201/docs (bearer token required)
#    Catalog API   → http://localhost:9001/products
#    OTLP endpoint → localhost:4317 (gRPC) / 4318 (HTTP)

# 5. Tear down (deletes local data volumes)
make infra-down
```

Run the test suite (mirrors CI):

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest            # unit suite; PostgreSQL integration runs in hosted CI
ruff check backend demoapp
```

Frontend console:

```bash
cd frontend && npm install && npm run dev   # http://localhost:3030
```

## 6. Documentation

| Document | Purpose |
|---|---|
| [docs/README.md](docs/README.md) | **Documentation index** — navigation hub. |
| [docs/project/](docs/project/) | **Project** — proposal & roadmap. |
| [docs/planning/](docs/planning/) | **Planning** — feature scope, product vision, phases & gates, timeline, decision log. |
| [docs/architecture/](docs/architecture/) | **Architecture** — system design, autonomy model, telemetry model, deployment intelligence, UML set, ADRs. |
| [docs/contracts/](docs/contracts/) | **API contracts** — OpenAPI set + contract-drift guard. |
| [docs/development/](docs/development/) | **Development** — conventions, local setup & tech stack. |
| [docs/operations/](docs/operations/) | **Operations** — evaluation metrics & protocol. |

## 7. Core Research Question

> **Can an AI-assisted SRE platform reduce incident detection and recovery time while
> accurately identifying root causes and safely automating predefined remediation actions
> in cloud-native applications?**

## 8. Scope Boundary

AegisSRE is **not** a general-purpose autonomous agent administering arbitrary production
infrastructure. Autonomy is constrained by:

- predefined tools (read-only telemetry access; scoped execution actions);
- least-privilege permissions;
- remediation policies (risk-classified, reversible actions only);
- human approval for high-risk operations;
- complete audit logging;
- post-remediation verification.

## 9. Naming Note

Python packages, container names, and infra identifiers use the `aegissre`
prefix. They were renamed from an earlier `aegisdeploy` working title on
2026-11-22; checkouts from before that date should reinstall editable packages
and rebuild local images.

## 10. Conventions & License

See [docs/development/contributing.md](docs/development/contributing.md) for development
conventions. Licensed under the [MIT License](LICENSE). Copyright © 2026 Navin Jairam
(Lucifer-Newstar).
