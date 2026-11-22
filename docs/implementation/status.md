# Implementation and acceptance ledger

Updated: 2026-11-23. This ledger separates code from demonstrated acceptance.
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

Local checks: 94 tests pass; two PostgreSQL-only tests are deliberately skipped
without an isolated test database. Ruff, strict typing, contracts, YAML and docs
links are checked. Hosted PostgreSQL and Compose results must pass before merge.
The complete telemetry worker, gateway, LLM/RAG, console and kind bootstrap remain
subsequent work. This does not declare milestone 2 as a whole complete.

## Milestone 2b: transport reliability (worker integration still ahead)

The Redis library now has real server-clock retention, pending-entry reclamation
for crashed consumers, bounded reads and explicit poison-message quarantine.
The original count-based approximation of a seconds TTL has been removed.
Housekeeping can trim idle streams too. Unit regressions and a fresh actual-Redis
CI gate cover this behavior. The telemetry worker and transactional outbox delivery
are not yet wired by this library-only step.

## Milestone 2c: live telemetry runtime

Implemented collectors now read fixed, service/environment-scoped Prometheus
rates, histograms and process gauges, plus registry health/SLO metadata and real
deployment envelopes. Process CPU/memory are exported by each demo service.
Missing, stale, non-finite or zero-traffic measurements cannot prove recovery.
The recovery-window SLI is not labelled as 30-day availability/error budget.

The runtime stages inputs in PostgreSQL, publishes via the transactional outbox,
consumes Redis with commit-before-ACK, reclaims crashed consumers, quarantines
permanent poison/conflict/order failures, and emits audit/domain events back to
canonical streams. Unexpected internal/storage errors remain pending. Anomaly
windows now begin at the actual oldest baseline sample, not a guessed duration.

The reliability API has a non-root image, runtime-only pinned dependencies,
protected readiness/progress endpoints and Compose wiring. Published local ports
are loopback-only. Compose requires an operator-supplied token and fixes the
executor to simulation. Single-process embedded runtime is supported; distributed
execution ownership and the authenticated console gateway are still ahead.

Local checks: 133 tests, Ruff, strict mypy, YAML and API contracts. A dedicated
hosted gate starts the actual runtime, observes real Prometheus/deployment data,
checks controlled Redis-to-incident/outbox/poison fixtures, restarts the API and
checks persisted business state plus pending-entry recovery. Those fixtures are
transport proof, not the ten-fault chaos/evaluation acceptance benchmark.

Earlier merged transport/storage proofs: [PR 2](https://github.com/Lucifer-Newstar/AegisSRE/pull/2)
and [PR 3](https://github.com/Lucifer-Newstar/AegisSRE/pull/3). The live gateway,
LLM/RAG/tool suite, full console, cluster bootstrap and evaluation remain open.

## Milestone 2d: authenticated API entrypoint

A compiled-route FastAPI gateway now fronts the existing APIs with explicit
bearer auth, shared Redis-backed rate windows, bounded bodies/responses, fixed
origins, redirect rejection and request correlation. Gateway writes bind audit
actors to the configured token principal. Backend credentials and cookies are
not copied from caller requests; upstream cookies are not retained. Redis failure
closes access. The image is non-root and disables proxy-header trust by default.

Local checks: 145 tests pass, with strict mypy/Ruff and eight API contracts. The
hosted runtime gate also exercises actual gateway auth, routing, correlation and
approval of a controlled CI incident, without executing a remediation.

This is the API boundary, not the completed console login. The existing console
still calls its old data layer and still has explicit mock scaffolding. Session
security, switching all console reads/writes through the gateway, internal
metadata auth/network hardening and production cluster proof remain open.

## Milestone 2e: scoped logs and trace evidence

Per-application instrumentation now owns its providers and service-scoped log
handler without replacing process globals. It is attached before ASGI startup,
flushes on shutdown (including startup failure), and places the current trace ID
in JSON log bodies. The order-to-cart request preserves W3C trace context.
Metrics use route templates rather than raw resource IDs and count uncaught 500s.
The demo and metadata images build from the repository root for this shared code.

Fixed-origin read-only Loki and Tempo readers enforce service/environment scope,
three-minute windows, response/time/cardinality limits, validated trace IDs and
an attribute allowlist. One service is sampled per collector tick. Where a log
has a trace ID, the collector fetches that exact trace, then stages both through
the existing durable outbox/Redis delivery. Missing stores are reported rather
than replaced with sample telemetry. Loki explicitly indexes the low-cardinality
service/environment resource attributes; trace IDs remain structured data.

Local checks: 159 passing tests, with Ruff, strict mypy, YAML and API contracts.
The hosted Compose gate also proved a real HTTP request's OTLP log and server
span share a trace ID after collection into the event database. This gate is
pipeline proof, not the ten-fault chaos benchmark or an AI accuracy claim.
Kubernetes event collection, the remaining evidence tools, LLM/RAG/Ask and the
complete console remain open.

## Milestone 2f: knowledge retrieval and operator runbooks

Ten packaged fault-specific runbooks and ten heuristic pattern documents now
have a scoped, versioned chunk index. PostgreSQL uses real `vector(768)` storage
and pgvector cosine search. SQLite is an explicitly named small-corpus fallback.
Embeddings are local lexical hashing, not a neural model or a paid model call.

A separate index task refreshes selected service metadata and verified-closed
incidents. Network reads and embedding work happen outside SQL transactions.
Deleted services/removed runbooks are dropped from retrieval. Cited snapshots
include document hashes, indexed times and versioned chunk IDs. Closed cases
retain cause uncertainty and simulation labels.

Authenticated runbook list/detail, scoped search, index status and read-only
incident-context APIs are routed through the gateway. Retrieval does not grant
approval or change an executable plan. Existing database migration cautions and
operating details are in [Knowledge retrieval](../operations/knowledge.md).

Local checks: 164 passing tests, four external-server tests deliberately skipped
locally, Ruff, strict mypy, YAML and eight API contracts. The authored ten-query
retrieval regression passes its recall@5 threshold, but is not the real chaos
benchmark. Hosted actual pgvector/vector-distance/persistence and Compose
retrieval/citation checks passed on PR7 before its ordinary all-green merge.
Live model acceptance, the console viewer and real-fault retrieval evaluation
remain open.

## Milestone 2g: read-only Ask and guarded investigation

Seven fixed read-only tools now return scoped event/knowledge snapshots with
visible calls, source references, observed/index times and missing/stale status.
Authenticated Ask and incident-investigation APIs use those snapshots. Optional
bounded Ollama/OpenAI-compatible adapters require explicit model configuration;
remote evidence egress is off by default. Disabled inference produces a clearly
labelled evidence-only readout, not fake model output.

Durable shared request reservations precede inference, including failed attempts.
Calls run outside SQL transactions and the telemetry worker. Structured answers
must cite supplied IDs; a cause hypothesis needs a non-stale observation. The
model cannot change a plan, approval, policy or execution state. Incident sidecar
writes reject changed revisions and expired snapshots. The initial milestone read current service evidence; milestone 2h below adds
historical incident-window reconstruction.

Local checks: 197 passing tests, five external-server tests skipped locally,
Ruff, strict mypy, YAML and eight API contracts. New hosted gates exercise actual
PostgreSQL concurrent quota reservations and real gateway Ask citations against
persisted collected metrics. Model transport tests use explicit mocks, and the
Compose gate deliberately disables inference. None are live model/accuracy proof.
See [Read-only intelligence](../operations/intelligence.md) for egress, request
limits, redaction limits, failure states and configuration.

## Milestone 2h: historical evidence and honest timing

Incident investigation now uses a bounded detection-time window and preserves
qualifying-event references before selecting other evidence. Later recovery
measurements cannot replace the incident's anomaly. Source timestamps with
mixed UTC offsets sort/filter as instants on SQLite and PostgreSQL without
rewriting old data. The capture timestamp remains the actual read time.

Historical retrieval excludes the target incident, later-indexed closed cases
and current service metadata. Existing deterministic diagnosis prose is not fed
back as the model's question. Newer completed snapshots cannot be overwritten by
older in-flight results. These guards do not replace a frozen held-out corpus.

Postmortems separate fault-onset research MTTR from incident duration. Unknown
onset and invalid timestamp intervals stay null. The evaluation protocol now
matches the core requirement of at least ten runs per fault and records censored
runs rather than inventing successful durations or manual baseline times.

Local checks: 204 passing tests, six external-server skips, Ruff, strict mypy and
API contracts. Hosted tests additionally exercise actual PostgreSQL offset/window
queries and reconstruct a historical incident through the running gateway using
explicit synthetic CI history. This is wiring proof, not a real fault, model run
or accuracy benchmark. PR8's actual quota and evidence-only Ask gates passed
before its nine-check ordinary merge.

## Milestone 2i: optional read-only Kubernetes event source

An independently scheduled, disabled-by-default source reads one configured
namespace over verified HTTPS using a projected service-account token. It maps
Deployment/ReplicaSet/Pod UIDs to allowlisted demo services and stages selected
events through the existing durable delivery path. Names alone cannot attribute
recreated objects. Missing/unmapped events remain unknown, not healthy.

Authentication, response/list/time bounds, token rotation, failed-source readiness
and stop-on-throttling/access-denial behavior are explicit. Separate example
namespace Roles grant only list permissions, with no Secret, exec or workload
write permission. See [Kubernetes evidence](../operations/kubernetes-evidence.md)
for the broader namespace read scope and current attribution limits.

Local checks: 222 passing tests and six real-server skips, with Ruff, strict mypy,
YAML and API contracts. Source tests use explicit HTTP mock transports; background
wiring uses a fake worker. No existing cluster was contacted. Actual kind,
least-privilege behavior and fault capture remain acceptance work, not a claimed
live Kubernetes proof.

## Milestone 2j: actual isolated Kubernetes evidence gate

The hosted [kind evidence job](https://github.com/Lucifer-Newstar/AegisSRE/actions/runs/45034540800/job/137245233522)
passed on head `c54a97b59caa9f515f063543ed1bc77c03381106` before this
ledger update. It built the packaged incidents image, created a new disposable
runner-local kind cluster, and captured a real `BackOff` warning through the
production reader using its projected service account and verified TLS. The
same Pod UID had an actual exit-42 process termination and restart. The Job
confirmed RBAC denials for Secret listing, another namespace's Pods, and a
server-side dry-run deployment creation probe. The denial check distinguishes
RBAC from an admission rejection. Captured evidence deduplicated in the actual
SQLite outbox and survived closing/reopening its repository. The job then deleted
the cluster it had created.

Tool downloads have checked SHA256 pins, the node image is digest-pinned, and all
kubectl calls explicitly name the isolated kubeconfig/context. Cleanup requires
this CI run/attempt/job's marker. Tests cover ambient-context refusal,
pre-existing-cluster refusal, stale ownership and checksum mismatch. The fixture
runs non-root under restricted Pod Security with bounded resources and a
read-only root filesystem. No existing user cluster was selected or contacted.

Local checks: 228 passing tests, six real-server skips, Ruff, strict mypy across
111 source files, YAML and API contracts. CI now has ten independent jobs. This
narrow actual-cluster gate is not full D1 bootstrap, in-cluster Redis transport,
real-model acceptance, remediation proof or the ten-fault evaluation. The
existing actual PostgreSQL/Redis and complete Compose checks remain separate.

## Milestone 2k: direct metadata authentication

Registry and deployment routes now use distinct internal read/write bearer keys.
No production defaults are provided. Only GET health/metrics remain public;
readiness, data and docs/schema need a key. Read-only credentials cannot mutate
metadata. Authentication precedes bounded request-body collection, including
chunked bodies, and malformed/duplicate headers fail closed. Local no-key mode
must be explicitly enabled and is forced off by Compose.

The gateway replaces caller keys with its internal metadata operator key. The
collector/indexer receive only the read key and attach it only to their fixed
metadata calls. Owned clients ignore ambient proxy settings and refuse redirects;
the evidence reader also refuses cookies and compressed responses. Metadata
images now run non-root, and Kubernetes examples use Secret-backed keys, local
authenticated readiness probes and a read-only root filesystem.

Local checks: 243 passing tests, six external-server skips, Ruff, strict mypy
across 113 files, YAML and API contracts. Hosted metadata and full-runtime gates
must additionally pass actual auth/read/write/persistence and collection checks
before merge. This is service authentication, not multi-tenant isolation,
production security approval or full kind bootstrap. The console remains a
labelled scaffold until its own authenticated gateway/session integration lands.
See [metadata authentication](../operations/metadata-auth.md).

## Feature-by-feature status

| ID | Implementation state | Acceptance still required |
|---|---|---|
| A1 Observability | Scoped metrics/health/deployment/log/trace collectors, UID-scoped Kubernetes source, durable delivery, hosted trace/log join and actual kind capture/RBAC proof | Full-stack startup timing and integrated kind runtime |
| A2 Registry | Durable CRUD, owner/SLO metadata and timed allowlisted probes implemented; hosted restart proof passed | Live console integration and full-stack timing |
| A3 Detection | Statistical + Isolation Forest code and unit tests | Held-out ten-fault precision/recall/F1 and measured detection latency |
| A4 Incidents | Lifecycle, Redis consumption/outbox, append-only audit and API implemented | Measured live timing and timeline UI |
| A5 Evidence/RCA | Fixed read-only tool suite, cited deterministic hypotheses, optional structured inference and revision-safe sidecars | Actual model/accuracy evaluation, broader real-fault evidence and postmortem UI |
| A6 Policy | Versioned typed policies, risk matrix and hard execution bounds | Runtime policy update, complete action matrix and safety evaluation |
| A7 Approvals | Approve/reject/defer API and audit implemented | Authorized console flow, impact view and click-count check |
| A8 Autonomy | Conservative decision gates, kill switch and executor code | Auto scheduler, least-privilege cluster integration, eligible-action success rate |
| A9 Recovery | Live fresh-metric + health/error/latency/SLI gate, timeout escalation | Cancellation/undo, longer-window budget context and ground-truth accuracy evaluation |
| A10 Dashboard | Existing four-page scaffold | Live overview, service/incident details, approvals and honest MTTD/MTTR |
| A11 Chaoslab | Catalog's existing fault-hook stub | All ten isolated faults, restoration and experiment manifests |
| A12 Evaluation | Existing protocol | Reproducible >=10 runs per fault, baseline comparison, mean/std report |
| B1 RAG | Scoped pgvector retrieval, local lexical embeddings, incremental indexing, RCA context and hosted actual-vector proof | Recall@5 on real evaluation faults |
| B2 Ask Aegis | Authenticated API, seven read-only tools, visible citations/freshness, disabled/failed inference labels and no write tools | Actual chosen-model acceptance and console view; hosted evidence-only gate passed on PR8 |
| C1 Eight pages | Four-page scaffold | Complete live eight-page console and UI checks |
| C3 Runbooks | Ten packaged guides, indexing and authenticated list/detail/context APIs | Live console viewer and incident links |
| C4 Postmortems | Verified-closure API implemented | Viewer, evidence/timeline/action rendering and metrics |
| C5 Audit | Durable append-only store, transactional Redis emission and filtered API implemented | Console viewer and filtering |
| D1 kind | Existing app manifests and actual isolated reader/RBAC/crash gate | Full dependencies, least privilege across the full stack, kind boot and behavior checks |
| D5 CI/CD | Existing lint/tests/build checks; reliability tests added | Publish workflow and agreed registry verification |
| D6 SLOs | Existing dashboard/alert configs | Live per-service panels, multiwindow burn alerts, firing checks |
| E2 Comparison | Not implemented | Real comparative results; no invented human-response timings |
| E4 Documentation | This milestone and contracts recorded | Continue updating evidence and limitations at each milestone |
| DI-1 Tracking | Durable producer-time history, conflict-safe idempotency and live polling into the reliability loop implemented | Deployment hook workflow and per-service timeline |
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

## Milestone 3a: observed deployment windows and honest CFR

Deployment lifecycle events can now carry an explicit logical identity and an
aware producer start without breaking replay of older stored envelopes. The
reliability transaction persists 180-second windows, source-event mappings,
observations and one idempotent `rollout.bad` domain event. Separate actual
flag/source clocks avoid presenting a historical fixture as fast detection.
Missing baselines, health, identity or unambiguous attribution cannot manufacture
healthy deployments or a complete CFR denominator. Late evidence invalidates
stale healthy results. Counts use SQL aggregates instead of bounded history.

Protected gateway reads expose rollout state and a scoped summary. This is an
observed-outcome foundation for DI-4/DI-7, not predictive risk/canary scoring,
causal proof or authority to execute a rollback. Detailed rules and proof limits
are in [deployment windows](../operations/deployment-windows.md).

Local checks: 264 passing tests, seven actual-server tests deliberately skipped
without their external services, strict mypy across 116 files and Ruff/contracts.
Hosted gates must pass before merge: actual PostgreSQL grouping, counts and
reopen; actual metadata-to-runtime collection, authenticated gateway reads,
application restart and Redis `rollout.bad` publication from labelled synthetic
CI inputs. These gates do not establish real-fault accuracy or three-minute
acceptance. DI-2/DI-6, remaining correlation/rollback integration, the complete
console, kind bootstrap and measured full acceptance remain open.

Project positioning now names the existing security controls as DevSecOps and
keeps the small planned MLOps scope to risk/canary scoring. Full training,
registries and drift pipelines are v2 ideas. Model selection, downloads, remote
inference disclosure and spending remain unapproved.

## Milestone 3b: complete local-demo kind assembly

The infra-root Kustomization now assembles all sixteen current Compose services
from the existing application bases plus the runtime, gateway, persistent stores
and observability workloads. ConfigMap generators use the exact shared infra
files, rather than duplicated configs. Six stores have PVCs; required service,
operator, database and Grafana credentials come from pre-created Secrets.

The runtime uses a dedicated projected-SA/TLS evidence reader with list-only
namespace permissions. Other Pods do not mount Kubernetes credentials. The
executor remains simulation and model inference stays disabled. Kubernetes
lists now handle up to five bounded pages, sharing the original 1MB resource
budget and ten-second collection deadline. Partial or unsafe pagination still
fails closed. The console binds explicitly on all Pod interfaces, without
changing its unfinished mock/session limitations.

Local checks: 276 passing native tests, seven explicit server-only skips,
strict mypy across 118 files, Ruff, 68 YAML files, docs links and API contracts.
Static/native checks cover image parity, persistent mounts, source config
paths, no external Services, credentials/evidence boundaries, owner/context
checks and bounded pagination. Offline Kustomize rendering produces 49 resources.
The added hosted gate must pass before merge: all sixteen workloads ready,
actual collection/log-trace/retrieval/gateway/Redis behavior, two application
restarts, projected-SA/TLS success, denied evidence-account writes/Secret access,
and Postgres Pod replacement without losing its PVC-backed metadata record.

This is demo infrastructure and running-service proof, not production tenancy,
real remediation, ten-fault chaos, numerical evaluation or the complete console.
The [kind operating guide](../operations/kind-platform.md) names those limits.
No paid cloud resources, model selection or inference are part of this change.


## Shop order persistence foundation

Order-service replaces its process dictionary with committed SQL storage.
Compose/kind wire a separate shop PostgreSQL server, identity and volume; the
platform evidence database is not its dependency. Database health is real and
connection/statement waits are bounded. Readiness/domain calls fail 503 while
liveness remains up; a cart transport error is no longer mislabeled empty-cart.
SQLite remains an explicit development/test default, not production persistence.

Native tests include file-backed store recreation, bound lookup keys, dependency
failure behavior and an actual closed-port connection failure. The full-platform
kind gate is extended to require committed order preservation across app restart
and a real isolated shop database outage/restoration, while checking the platform
stays ready. Hosted proof must pass on the exact PR head before merge. This does
not complete the chaos CLI, its ten fault types, Redis carts, or any measured
accuracy/autonomy/MTTR acceptance threshold.


## Shop cart persistence foundation

Cart-service now uses its own Redis server/PVC, distinct from platform transport,
in Compose and kind. Atomic hash increments avoid read/modify/write lost updates;
AOF/always is configured in both runtimes. Dependency failure is readiness/domain
503 with no local/empty-cart fallback; process liveness remains independent.
The default empty-URL local store is development-only. No Redis authentication,
network tenant isolation or idempotent retry contract is implied.

The kind gate must prove cart retention after app restart and real shop Redis
outage/restoration while platform and saved order reads remain healthy. Native
checks alone do not establish the hosted proof. These two isolated dependencies
are prerequisites for honest fault experiments, not completion of A11/A12 or any
accuracy/MTTR/autonomy acceptance target.

## Authenticated console foundation

The console now uses encrypted HttpOnly sessions and the fixed authenticated
gateway instead of unauthenticated metadata calls or mock fallbacks. Missing
operator configuration fails closed. Mutations use exact-origin+CSRF checks;
approval decisions are distinct from execution. Tokens are never sent to client
components or browser storage. UI routes expose current API records and visible
errors/unknown data, with no fabricated research timers.

Session tests and actual Next build pass. Local browser checks exercised login,
protected routes, cookie properties, token non-disclosure and cross-origin
rejection against a synthetic HTTP fixture. [Inspected screenshots](../screenshots/console-foundation/README.md)
are explicitly fixture-only visual evidence. The actual owned-kind gateway/page
proof must pass before merge. Charts/anomaly shading, structured reports/export,
24h history, SLO panels, risk/canary views and full interaction/visual acceptance
remain. Route presence alone does not establish C1 completion.
## Chaos hook and journal foundation, not ten-fault acceptance

The four shop images now include a separate opt-in fault-hook package. Normal
manifests leave it disabled. No HTTP controls are exposed; the owned runner
writes bounded expiring regular-file state. Native checks reject symlinks,
FIFOs, malformed/oversized/unknown control data. HTTP error and request delay,
bounded CPU and memory-pressure primitives are implemented; bounded pressure is
not actual memory exhaustion, and application delay is not packet shaping.

The initial CLI is restricted to the current newly owned CI kind fixture. It
uses explicit context/namespace, fixed shop targets, UID/label checks, exclusive
experiment markers and separate fsynced ground-truth journals. Restoration runs
on exceptions and handled termination, while unresolved runs retain their lock.
It records control application and restoration honestly, never inferred symptom
onset, verified recovery or invented evaluation metrics. Its fixed DB/Redis
operations use the isolated shop dependencies, not platform stores.

The actual kind gate must run and independently observe one HTTP fault/restore
through this CLI before merge. The other hook/runner operations still need real
cluster proof; crash, actual OOM, config error, faulty deployment and traffic-spike
experiments remain. A11/A12, measured accuracy/MTTR/autonomy and the full project
are not complete. Details and current operation matrix: [chaos CLI](../../chaoslab/README.md).
