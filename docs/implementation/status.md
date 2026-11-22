# Implementation and acceptance ledger

Updated: 2026-11-22. This ledger separates code from demonstrated acceptance.
The scope reference is [features.md](../planning/features.md). Cut and stretch
items retain their existing status. A passing unit test is not a measured
end-to-end reliability result.

## Milestone 1: reliability core

Implemented in `backend/services/incidents-service`:

- Typed v0.2 telemetry ingestion with finite metric values, bounded payloads,
  timezone-aware timestamps, idempotency and per-series ordering checks.
- Statistical novelty detection and Isolation Forest trained on preceding normal
  samples. Baselines are isolated by service, environment, metric, labels and unit.
- Transactional event, incident, audit and outbox persistence. PostgreSQL is the
  deployment backend; SQLite is the independent local/test backend.
- Incident lifecycle, evidence-linked deterministic cause ranking, approval /
  rejection / deferral, conservative policy checks, cooldown and rate limits.
- Explicit simulation and disabled-by-default scoped Kubernetes execution.
  An execution attempt is persisted before external I/O; an interrupted attempt
  is escalated for reconciliation rather than blindly retried.
- Recovery needs fresh post-action samples for every affected series and fresh
  health, error, latency and SLO checks. An elapsed deadline escalates.
- Bearer-authenticated API, kill switch, audit and verified-closure postmortems.

This milestone does **not** constitute the finished platform. It has no LLM yet,
no background ingestion, no live console integration, and no full-stack proof.
No cloud resources were launched. Simulation never changes a workload or claims
to prove that a real workload recovered.

### Checks run for milestone 1

- 81 Python tests, including 27 new reliability tests.
- Ruff and strict mypy across backend and demo app.
- Contract drift guard across seven service contracts; all YAML parses.
- PostgreSQL integration, container startup, real cluster actions and evaluation
  acceptance targets are not yet verified at this milestone.

## Milestone 2a: durable metadata integration

Implemented on the runtime-integration branch:

- Shared transactional document storage for registry/deployment metadata.
- Registry create/read/update/delete, owner/SLO metadata, persistent deletion,
  bounded allowlisted probes and a 15-second background health cadence.
- Real storage readiness, durable deployment history and producer-time ordering.
  Startup no longer invents deployments for other services.
- Root-context images with the local storage package, PostgreSQL wiring in
  Compose, loopback-bound metadata APIs and Secret references in K8s workloads.
- A hosted integration gate that starts actual containers, seeds through their
  HTTP APIs, restarts application processes and checks persistence/deletion.
- The Prometheus alert file is now mounted where its configuration expects it.

Local checks: 91 tests pass; two PostgreSQL-only tests are deliberately skipped
without an isolated test database. Ruff, strict typing, contracts, YAML and docs
links are checked. Hosted PostgreSQL and Compose results must pass before merge.
The complete telemetry worker, gateway, LLM/RAG, console and kind bootstrap remain
subsequent work. This does not declare milestone 2 as a whole complete.

## Feature-by-feature status

| ID | Implementation state | Acceptance still required |
|---|---|---|
| A1 Observability | Existing stack; core input and durable outbox added | Live collectors, Redis delivery/recovery, trace joins, startup timing |
| A2 Registry | Durable CRUD, owner/SLO metadata and timed allowlisted probes implemented | Hosted restart/storage checks and live console integration |
| A3 Detection | Statistical + Isolation Forest code and unit tests | Held-out ten-fault precision/recall/F1 and measured detection latency |
| A4 Incidents | Lifecycle, grouping, append-only audit and API implemented | Redis consumption, live timing and timeline UI |
| A5 Evidence/RCA | Persisted evidence and cited deterministic hypotheses | Full read-only tool suite, LLM adapter, ranked evaluation, postmortem UI |
| A6 Policy | Versioned typed policies, risk matrix and hard execution bounds | Runtime policy update, complete action matrix and safety evaluation |
| A7 Approvals | Approve/reject/defer API and audit implemented | Authorized console flow, impact view and click-count check |
| A8 Autonomy | Conservative decision gates, kill switch and executor code | Auto scheduler, least-privilege cluster integration, eligible-action success rate |
| A9 Recovery | Sample + health/error/latency/SLO gate, timeout escalation | Live collection, cancellation/undo and ground-truth accuracy evaluation |
| A10 Dashboard | Existing four-page scaffold | Live overview, service/incident details, approvals and honest MTTD/MTTR |
| A11 Chaoslab | Catalog's existing fault-hook stub | All ten isolated faults, restoration and experiment manifests |
| A12 Evaluation | Existing protocol | Reproducible >=10 runs per fault, baseline comparison, mean/std report |
| B1 RAG | Not implemented | pgvector, indexing, cited retrieval and recall@5 |
| B2 Ask Aegis | Not implemented | Read-only tools, citations, tool-call view and no write exposure |
| C1 Eight pages | Four-page scaffold | Complete live eight-page console and UI checks |
| C3 Runbooks | Not implemented | List, viewer, indexing and incident links |
| C4 Postmortems | Verified-closure API implemented | Viewer, evidence/timeline/action rendering and metrics |
| C5 Audit | Durable append-only store and filtered API implemented | Console viewer and filtering |
| D1 kind | Existing app manifests | Full dependencies, least privilege, kind boot and behavior checks |
| D5 CI/CD | Existing lint/tests/build checks; reliability tests added | Publish workflow and agreed registry verification |
| D6 SLOs | Existing dashboard/alert configs | Live per-service panels, multiwindow burn alerts, firing checks |
| E2 Comparison | Not implemented | Real comparative results; no invented human-response timings |
| E4 Documentation | This milestone and contracts recorded | Continue updating evidence and limitations at each milestone |
| DI-1 Tracking | Durable producer-time history and conflict-safe idempotency implemented | Live deployment hook and per-service timeline |
| DI-2 Risk | Not implemented | Trained risk scorer, pre/post inputs and held-out recall |
| DI-3 Correlation | Evidence-timing correlation implemented | Deployment attribution evaluation and UI |
| DI-4 Bad rollout | Not implemented | Window evaluator and measured detection bound |
| DI-5 Rollback | Recommendation, approval/policy and scoped executor code | Live revision mapping, safe-auto predicates and verified recovery rate |
| DI-6 Canary | Not implemented | Stable/canary comparison, demo rollout and UI |
| DI-7 CFR | Not implemented | Analytics, trends, deployment postmortems and evaluation |

## Next milestones

1. Runtime integration: authenticated gateway, collectors, event delivery,
   durable registry/deployments, PostgreSQL/Redis/Compose proof.
2. Intelligence: read-only evidence tools, pgvector retrieval, configurable LLM,
   deployment risk/correlation/canary analytics, policy and safe-auto integration.
3. Product and experiments: live console, ten-fault chaoslab, honest evaluation,
   kind integration, screenshots of the actual running system.
4. Acceptance pass: complete feature matrix, security/failure-path review, clean
   full-stack CI, verified docs and remaining limitations.

The target is November 25, with quality taking priority over the date. External
LLM credentials/model choice and authorization for any real cluster are separate
configuration decisions. No real infrastructure action is assumed.
