# Feature Scope & Acceptance

> **Purpose:** define what gets built, what each item depends on, and how completion is checked. This is the scope reference; phase order and gates are in [phases.md](phases.md).
>
> **Scope status:** `Core` = approved project scope · `Stretch` = optional only if the core is on schedule · `Cut` = not planned. Reopening a cut item requires a decision-log entry.

---

## Final release clarification, November23

The owner approved a genuine smaller comparison:30 manual trials with Navin as
the solo human operator, paired with30 Aegis trials, three repetitions per fault. This replaces
the ten-per-fault release cohort requirement below, without pretending it meets
that original larger research design. Results must say small sample and retain
all failed/censored observations. Use the explicit small profile in
[the evaluation guide](../../evaluation/README.md). Runs stay local/small; no
hosted matrix or spending is approved.

No language-model inference or deeper MLOps build is required for this final
release. Those may be described as unbuilt roadmap ideas only. Statistical/IF
detection, evidence-only reasoning/Ask, pgvector retrieval and the planned
risk/canary scope are retained. No v2 implementation is being commissioned.
Image publication is approved for GHCR under Lucifer-Newstar/AegisSRE with
anyone-can-read access, only when the work is ready.

## 1. How to read the catalogue

- **Feature ID** identifies the item. `A–E` and `DI` are separate ID families; for example, **D1** means Kubernetes, while **DI-1** means deployment tracking.
- **Priority tier** (P0/P1) is a feature priority, not development phase P0/P1/P2.
- Each item is separated into **Outcome**, **Needs**, and **Done when**.
- Numeric targets are acceptance thresholds, not promises about production-grade capability.
- **Build status** is tracked in [phases.md](phases.md) and the roadmap — this file defines the target, not the current state.

## 2. Approved scope at a glance

| Group | Included items | Purpose |
|---|---|---|
| **A · Core platform (P0)** | A1–A12 | Observe, detect, investigate, act safely, verify, and evaluate. |
| **B · AI depth (P1)** | B1–B2 | Grounded knowledge retrieval and read-only assistant. |
| **C · Product / UX (P1)** | C1, C3–C5 | Complete console and supporting views. |
| **D · DevOps / Cloud (P1)** | D1, D5–D6 | Kubernetes, CI/CD, and SLO monitoring. |
| **E · Academic (P1)** | E2, E4 | Comparative evaluation and milestone documentation. |
| **DI · Deployment Intelligence** | DI-1–DI-7 | Understand deployment risk, impact, rollback, canaries, and outcomes. |

**Demo application:** AegisShop, the project's own instrumented microservices app. Its service map is in [phases.md §7](phases.md#7-demo-application-aegisshop).

### Not planned

| Item | Status / reason |
|---|---|
| B3 · LoRA/QLoRA fine-tuning | **Stretch** in the final buffer only; drop it if core gates slip or hardware is unsuitable. |
| B4 · Time-series forecasting; B6 · incident clustering | **Cut:** not needed for the core research question. |
| C2 · topology map; C6 · notifications | **Cut:** not required for the agreed demo. |
| D2 · GitOps; D3 · cloud Terraform; D4 · chaos-mesh | **Cut:** local Kubernetes and the deterministic chaos lab cover the need. |
| E3 · literature survey; E5 · user study | **Cut:** outside the agreed evaluation plan. |

No cut feature is implicitly included as “nice to have.”

---

## 3. Tier A — Core platform (P0)

### A1 · Observability pipeline
- **Outcome:** collect app telemetry through OpenTelemetry; route metrics to Prometheus, logs to Loki, traces to Tempo; carry Kubernetes and deployment events on the shared event layer using the [telemetry envelope](../architecture/telemetry-model.md).
- **Needs:** shared infra stack.
- **Done when:** metrics appear in Grafana within 60 seconds of startup, logs are queryable, traces can be joined by `trace_id`, and required events are ingested.

### A2 · Service registry and health
- **Outcome:** API-managed service catalogue (owner, endpoints, SLOs) plus current health.
- **Needs:** A1.
- **Done when:** services can be created/read/updated/deleted through the API; health refreshes every 15 seconds; the console can read the result.

### A3 · Anomaly detection
- **Outcome:** detect unusual p95 latency, error rate, CPU/memory, and request rate using statistical baselines and Isolation Forest; publish `anomaly.score` events with model, threshold, window, and baseline context.
- **Needs:** A1–A2.
- **Done when:** precision, recall, and F1 are each at least 0.85 on the agreed chaoslab evaluation set; detection latency is under 60 seconds from fault onset.

### A4 · Incident manager
- **Outcome:** group anomaly events into incidents, assign severity, enforce `open → investigating → remediating → verifying → closed | escalated`, and retain an append-only timeline.
- **Needs:** A3.
- **Done when:** an incident is created within 30 seconds of its qualifying anomaly; invalid state transitions are rejected; timeline API is usable. Postmortem generation is delivered under A5/C4.

### A5 · Evidence and root-cause analysis
- **Outcome:** gather evidence through read-only tools (metrics, logs, traces, service health, deployment history, Kubernetes events, runbooks); return ranked cause hypotheses with citations and confidence; generate a postmortem when an incident closes.
- **Needs:** A1–A4; B1 retrieval context is integrated when available. RCA must still run against seeded evidence if retrieval is delayed.
- **Done when:** top-1 cause accuracy is at least 70% on evaluation faults, each hypothesis cites evidence, and a postmortem is available after closure.

### A6 · Remediation planner and policy engine
- **Outcome:** define actions (restart, rollback, scale, replace instance, config update, escalate), risk levels (low/medium/high/forbidden), and versioned policies. This component alone decides approval versus automatic execution.
- **Needs:** A4–A5.
- **Done when:** risk classification passes the agreed evaluation set with zero safety violations; policies can be changed without code edits.

### A7 · Approval workflow (Level 4)
- **Outcome:** let an authorized person approve, reject, or defer an action with an impact summary; record actor, reason, and decision.
- **Needs:** A6.
- **Done when:** a decision takes at most three UI clicks and every decision is audit-logged.

### A8 · Safe autonomous execution (Level 5)
- **Outcome:** run only policy-approved, low-risk, reversible actions automatically; enforce cooldowns, rate limits, and a global autonomy-mode kill switch.
- **Needs:** A6–A7.
- **Done when:** at least 80% of eligible evaluation actions succeed; the kill switch takes effect immediately; no policy-violating action runs.

### A9 · Recovery verification
- **Outcome:** check health, errors, latency, and SLO status after remediation; close only when recovered, otherwise escalate.
- **Needs:** A4 and A8.
- **Done when:** verdict accuracy is at least 90% against ground truth; no unrecovered incident is closed.

### A10 · Core dashboard
- **Outcome:** live overview, service detail, incident detail, and approvals views, including MTTD/MTTR and incident evidence.
- **Needs:** A2, A4–A7 APIs.
- **Done when:** core views render live API data; incident detail shows timeline, reasoning, and evidence. The complete eight-page scope is C1.

### A11 · Chaos lab
- **Outcome:** deterministic CLI fault injection for CPU saturation, memory exhaustion, container crash, database outage, network latency, HTTP 5xx, dependency failure, config error, faulty deployment, and traffic spike; restore state after each experiment.
- **Needs:** AegisShop.
- **Done when:** all ten faults are injectable; each run records fault label, start/end time, and restoration result for A12.

### A12 · Evaluation framework
- **Outcome:** compare conventional monitoring/manual response with AegisSRE on identical faults; automate MTTD, MTTR, RCA, autonomy, and summary statistics.
- **Needs:** A11 and E4.
- **Done when:** one documented command produces a reproducible report under the explicitly approved30-pair small-sample design, with mean ± standard deviation and censoring/coverage. The original ten-runs-per-fault design remains a clearly unmet larger study, not a claim.

---

## 4. Tier B — AI depth (P1)

### B1 · RAG knowledge base
- **Outcome:** index runbooks, prior incidents, service metadata, and known failure patterns in pgvector for retrieval by the reasoning layer.
- **Needs:** A4 and PostgreSQL/pgvector.
- **Done when:** relevant runbooks achieve recall@5 of at least 0.8 on evaluation faults and retrieved context is available to RCA.

### B2 · Ask Aegis
- **Outcome:** answer natural-language health questions using read-only tools; show tool calls and cited evidence. No write tools are exposed.
- **Needs:** B1 and the read-only tool layer.
- **Done when:** health/metric/log questions receive evidence-cited answers, tool calls are visible, and write-tool exposure is zero.

---

## 5. Tier C — Product / UX (P1)

| ID | Outcome | Needs | Done when |
|---|---|---|---|
| **C1** | Eight-page console: command center, service, incident, approvals, postmortem, runbooks, Ask Aegis, deployments. | A10, B2, supporting APIs | All eight pages work on live APIs and match [product-vision.md](product-vision.md). |
| **C3** | Runbook list and viewer linked to incidents. | B1 | Runbook opens in console from its incident link. |
| **C4** | Postmortem viewer. | A5 | Timeline, evidence, actions, and metrics render after incident close. |
| **C5** | Audit-log viewer. | Audit store | Audit entries can be filtered and inspected. |

---

## 6. Tier D — DevOps / Cloud (P1)

| ID | Outcome | Needs | Done when |
|---|---|---|---|
| **D1** | Run platform and AegisShop on kind using Kustomize bases (k3s fallback). | Containerized services | `kubectl apply` brings up the stack with behavior/config aligned to Compose. |
| **D5** | CI/CD: test, lint, build, publish images; deployment is optional. | Service components | PR pipeline is green and images are published to the agreed registry. |
| **D6** | Per-service SLO dashboards and burn-rate alerts. | A1 | Grafana panels are live and alerts fire in evaluation scenarios. |

---

## 7. Tier E — Academic (P1)

| ID | Outcome | Needs | Done when |
|---|---|---|---|
| **E2** | Compare conventional and AI-assisted workflows using MTTD, MTTR, and correctness. | A12 | Statistical results are documented and committed. |
| **E4** | Keep implementation, decisions, and results documented at each milestone. | All features | Milestone docs are current, linked, and understandable without verbal context. |

---

## 8. Deployment Intelligence (DI)

> Detailed design: [deployment-intelligence.md](../architecture/deployment-intelligence.md). DI is integrated into P2–P8; it does not add a phase.

| ID | Outcome | Needs | Done when |
|---|---|---|---|
| **DI-1** | Record deploy/rollback events; expose history and per-service timeline. | A1, envelope | Each deploy/rollback is recorded and history API is available at P2 gate. |
| **DI-2** | Score deployment risk before/after rollout. | DI-1, A3 | Every demo deployment gets a score; recall ≥0.7 on faulty-deploy faults. |
| **DI-3** | Attribute incidents to likely causing deployments. | A5, DI-1 | Top-1 correlation accuracy ≥0.8 on faulty-deploy faults. |
| **DI-4** | Evaluate anomalies in a deployment window and flag bad rollouts. | DI-1, A3 | `rollout.bad` is flagged within three minutes on faulty-deploy tests. |
| **DI-5** | Recommend rollback and execute only under the A6/A8 policy. | A6, A8, DI-4 | Health is restored in ≥80% of faulty-deploy runs, with zero safety violations. |
| **DI-6** | Compare canary and stable metrics to assess a progressive rollout. | D1, DI-4 | Demo canary is analyzed and result is visible in console. |
| **DI-7** | Calculate change-failure rate (CFR), show trends, and include deployment postmortems. | DI-1 for dashboard data; A12 for evaluation | CFR panel is live and the metric appears in evaluation report. |

---

## 9. Delivery map

| Phase | Feature IDs delivered or advanced |
|---|---|
| P2 | A1, A2, DI-1; console scaffold |
| P3 | A3, A4, DI-4 base |
| P4 | A5, B1, B2, DI-2, DI-3 |
| P5 | A6–A9, DI-5 |
| P6 (parallel) | A10, C1, C3–C5, D5, D6, DI-7 dashboards |
| P7 | D1, A11, DI-6 |
| P8 | A12, E2, DI-7 evaluation |

For acceptance gates and integration demonstrations, use [phases.md](phases.md).
