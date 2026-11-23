# AegisSRE

Telemetry-driven reliability and deployment intelligence, with policy-controlled
remediation and evidence-backed recovery checks.

A personal project by **Navin Jairam**
([@Lucifer-Newstar](https://github.com/Lucifer-Newstar)).

**Status: implementation and integration proofs are available; local comparative
evaluation and release publication are unfinished.**

[Scope](docs/planning/features.md) · [Current status](docs/implementation/status.md) ·
[Integration evidence](docs/implementation/product-acceptance-proofs.md) ·
[Documentation](docs/README.md)

## 1. What is implemented

- **Observability:** OpenTelemetry, Prometheus, Grafana, Loki and Tempo, with
  scoped metrics/log/trace evidence and Kubernetes/deployment events.
- **Reliability runtime:** statistical and Isolation Forest detection, durable
  PostgreSQL business state, Redis Streams delivery, incident lifecycle, cited
  deterministic cause ranking and postmortems. Missing evidence stays unknown.
- **Knowledge and Ask:** pgvector retrieval and read-only evidence tools. The
  final release uses evidence-only reasoning, not language-model inference.
- **Controlled remediation:** approval/reject/defer, versioned policy, cooldowns,
  rate limits, cancellation and observe-mode kill switch. Base configuration
  uses simulation. An opt-in scoped Kubernetes executor has real scale/rollback
  integration proofs, not measured recovery-accuracy claims.
- **Deployment intelligence:** frozen empirical/change-attribute risk estimates,
  rollout windows, revision context, observed stable/canary comparison and
  change-failure analytics. Predictive thresholds remain unmeasured.
- **Authenticated console:** command center, service and incident detail,
  approvals, postmortems, runbooks, Ask and deployments, with sessions,
  origin/CSRF checks, metric charts and explicit error/unknown states.
- **Chaos and evaluation:** ten bounded owned-fixture fault types, independent
  probes, real manual acknowledgements, archived baseline resets and reviewed
  cohort reporting. Timed cleanup is never credited as remediation.
- **DevSecOps:** separate read/write credentials, non-root containers, bounded
  API routes, RBAC, audit, and eleven CI jobs covering code, builds, storage,
  live collection and the complete disposable kind stack.

The [acceptance ledger](docs/implementation/status.md) distinguishes historical
milestones from current work. Integration fixtures and passing tests are not a
held-out study or a completed product acceptance result.

### Still required for completion

1. Validate Docker Desktop/WSL2 resources, one real laptop smoke and an isolated
   reset. The [Windows runbook](docs/development/windows-local-trials.md) is
   prepared but not yet validated on the target laptop.
2. Collect30 genuine manual/Aegis pairs, one human operator, three repetitions
   per fault. Preserve failed, censored and unknown outcomes. Disclose the small
   sample, non-blinding, learning/order effects and acknowledgement timing.
3. Review detector/RCA/retrieval/DI/recovery and autonomy results against the
   [acceptance targets](docs/planning/features.md). No benchmark numbers are
   supplied by the smoke tests.
4. Publish and pull-verify final GHCR images when the work is ready. Publication
   has not happened yet.

No live language model, model registry, training/drift pipeline or v2 build is
part of this final release. Those remain unbuilt roadmap ideas only.

## 2. Start here

| Goal | Guide |
|---|---|
| Run the development stack | [Quickstart below](#5-quickstart-local-development) |
| Understand what is proven | [Scoped integration proofs](docs/implementation/product-acceptance-proofs.md) |
| Run isolated local trials | [Windows/WSL2 setup](docs/development/windows-local-trials.md) |
| Compare real workflows | [Matched-session protocol](docs/development/matched-trials.md) |
| Produce a report from reviewed evidence | [Evaluation guide](evaluation/README.md) |
| Review the full agreed scope | [Feature acceptance](docs/planning/features.md) |

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
│   └── services/         registry, deployments, incidents, gateway and template
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
├── chaoslab/             Owned-fixture fault controller and control journals
├── evaluation/           Capture, solo timing, reviewed cohort and quality reports
├── scripts/              CI proofs, local trial setup and validators
├── docker-compose.yml    Local development stack (Compose now, K8s-ready)
└── Makefile              Common developer tasks
```

Detection, evidence reasoning and deployment intelligence live in the reliability
service. Separate `ml/` and `ai/` directories are not required to use them.

## 5. Quickstart (Local Development)

Prerequisites: Docker + Docker Compose v2. For running tests outside containers:
Python **3.12+** and Node.js 22.

```bash
# 1. Configure local credentials (preserve an existing .env)
test -f .env || cp .env.example .env
# Set AEGIS_API_TOKEN, distinct AEGIS_METADATA_API_TOKEN and
# AEGIS_METADATA_READ_TOKEN, and AEGIS_CONSOLE_SESSION_SECRET in .env.
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
#    Registry      → http://localhost:8101/services (service bearer key required)
#    Deployments   → http://localhost:8701/deployments (service bearer key required)
#    Incidents API → http://localhost:8201/docs (bearer token required)
#    Catalog API   → http://localhost:9001/products
#    OTLP endpoint → localhost:4317 (gRPC) / 4318 (HTTP)

# 5. Tear down (deletes local data volumes)
make infra-down
```

Run the local Python checks (external-service gates also run in CI):

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest evaluation/tests backend demoapp
ruff check backend demoapp scripts/ci chaoslab evaluation
```

Frontend console:

```bash
cd frontend && npm ci && npm run dev   # http://localhost:3030
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
