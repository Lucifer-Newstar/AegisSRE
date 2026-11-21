# Development Phases & Integration Gates

> **Purpose:** show the order of work and the proof required to finish each phase. Feature definitions are in [features.md](features.md); dates are in [timeline.md](timeline.md).
>
> A phase is complete only when its gate and integration checkpoint pass, tests/CI are appropriate, and documentation is updated. Dates are targets; gates are the completion rule.

---

## 1. How phase planning works

- **Phase:** a time-boxed delivery stage (P1–P8). Do not confuse these labels with feature priority tiers P0/P1.
- **Workstream:** a coherent slice of work inside a phase (observability, backend, frontend, AI/ML). Workstreams proceed in parallel against agreed contracts and mocks.
- **Gate:** the minimum working result required to finish a phase.
- **Integration checkpoint:** an end-to-end demonstration of that result with the workstreams connected.
- **Feature IDs:** refer to [features.md](features.md). `D1` is Kubernetes; `DI-1` is deployment tracking.

### Working rules

1. Commit shared API, event, and telemetry contracts before consumers implement against them.
2. Use mock servers, test producers, and seeded fixtures when a dependency is not ready.
3. Reserve the final 2–3 days of a phase for fixes, integration, and gate review; do not add scope then.
4. A passed gate and a decision-log entry open the next phase.

---

## 2. Phase summary

| Phase | Focus | Gate result | Integration checkpoint |
|---|---|---|---|
| **P1 · Foundation** ✅ | Repo, documentation, base stack, CI | Stack starts healthy; CI and docs checks pass. | Passed 2026-08-31. |
| **P2 · Observability + AegisShop v1** | A1, A2, DI-1, app v1, console scaffold | App telemetry is queryable; registry/health and deploy history work; console scaffold runs on mocks. | One command starts the app/platform; services appear in Grafana and console. MVP slice landed 2026-10-10. |
| **P3 · Detection + incidents** | A3, A4, DI-4 base | Injected fault produces anomaly and incident with timeline; target detection metrics pass. | Fault-to-incident demo. |
| **P4 · AI reasoning** | A5, B1, B2, DI-2, DI-3 | Cited RCA and read-only Q&A work; faulty deployment can be correlated. | Live incident shows evidence and reasoning. |
| **P5 · Remediation + autonomy** | A6–A9, DI-5 | Approval and safe-auto paths execute within policy and verify recovery. | Demonstrate one approval action and one eligible auto action. |
| **P6 · Product completion (parallel)** | C1, C3–C5, D5–D6, DI-7 dashboard | Eight console pages use live APIs; CI/CD, SLO, and CFR views work. | Live-data product walkthrough. |
| **P7 · Kubernetes + chaos lab** | D1, A11, DI-6 | Platform/app run on kind; ten faults produce ground truth; canary is analyzed. | Cluster demo with fault injection. |
| **P8 · Evaluation + report** | A12, E2, DI-7 evaluation | Reproducible evaluation report and demo materials are ready. | Final demonstration. |

P6 overlaps P5 in the calendar; it is a parallel product workstream, not a prerequisite that blocks the P5 gate.

---

## 3. Phase goals and gates

### P1 · Foundation — passed
- **Work:** repo structure, ADRs, Compose observability stack, CI, and planning docs.
- **Gate:** stack healthy, CI green, docs indexed.
- **Result:** passed 2026-08-31.

### P2 · Observability + AegisShop v1
- **Goal:** make the demo app observable and give every workstream a usable starting point.
- **Workstreams:**
  - **Observability:** A1 pipeline, Grafana dashboards, Compose wiring.
  - **Backend:** A2 registry/health, AegisShop backend, DI-1 history API.
  - **Platform design:** shared telemetry/event design, contracts, integration protocol.
  - **Frontend:** console scaffold and design system using mock data.
- **Gate:** AegisShop metrics/logs/traces are queryable; registry and health API respond; deploy events/history are recorded; console scaffold runs on mocks.
- **Checkpoint:** start app and platform together; verify services in Grafana and console.
- **Status:** MVP slice landed 2026-10-10 (registry, deployments, AegisShop cart/order/payment, Grafana overview, Compose/K8s wiring, console scaffold).

### P3 · Detection + incidents
- **Goal:** turn a controlled fault into a tracked incident.
- **Workstreams:** A3 detector and tuning; A4 incident state machine/timeline; metric plumbing and fault validation; service/incident console views with anomaly context.
- **DI work:** establish the DI-4 deployment evaluation window.
- **Gate:** CPU/latency test fault produces `anomaly.score`, then an incident within 30 seconds; precision/recall/F1 meet A3 thresholds on the agreed validation set.
- **Checkpoint:** run a fault-to-incident demo from the test hooks.

### P4 · AI reasoning
- **Goal:** explain incidents using traceable evidence.
- **Workstreams:** A5, B1, B2, DI-2, DI-3; evidence/incident APIs and deploy history; read-only query proxies; incident reasoning and Ask Aegis UI.
- **Gate:** top-1 RCA accuracy ≥70%; every hypothesis cites evidence; Ask Aegis answers a health question with citations; DI-3 top-1 accuracy ≥0.8 on faulty-deploy tests.
- **Checkpoint:** inspect a live incident in the UI and ask a question answered from live evidence.

### P5 · Remediation + autonomy
- **Goal:** execute permitted actions and prove recovery without bypassing safeguards.
- **Workstreams:** A6 implementation, A7 approval API, A9 verification API; policy/risk matrix, A8 mode and kill switch, verification logic, DI-5 policy; scoped restart/rollback/scale executors; approval UI and autonomy indicator.
- **Gate:** approve → execute → verify → close works; only allowed low-risk actions auto-run; low-risk rollback restores service; kill switch is immediate; safety violations = 0.
- **Checkpoint:** show one human-approved and one policy-approved automatic action end-to-end.

### P6 · Product completion (parallel)
- **Goal:** finish the console and operational views on real APIs while P5 proceeds.
- **Workstreams:** C1 eight pages, C3–C5; D5 pipeline, D6 SLOs, DI-7 dashboards; API polish/client generation; SLO definitions and integration.
- **Gate:** all eight pages use live data; CI/CD is green; SLO and burn-rate views work; CFR dashboard is live.
- **Checkpoint:** walkthrough of the product using live data.

### P7 · Kubernetes + chaos lab
- **Goal:** run the integrated platform in a reproducible cluster and validate controlled experiments.
- **Workstreams:** D1 kind/Kustomize, A11 implementation, DI-6; fault specs/manifests/ground truth; AegisShop fault hooks and hardening; cluster UX pass.
- **Gate:** platform and app start on kind; all ten fault types inject and restore state with labeled ground truth; canary analysis appears in console.
- **Checkpoint:** cluster-wide demo with a live fault injection.

### P8 · Evaluation + report
- **Goal:** answer the research question with reproducible evidence.
- **Workstreams:** A12/E2 and results; at least ten runs per fault; demo video/screenshots; API docs; cluster stability.
- **Gate:** report includes at least ten runs per fault type and MTTD, MTTR, RCA, autonomy, and CFR results with mean ± standard deviation; demo materials and milestone docs are complete.
- **Checkpoint:** final demonstration.

---

## 4. Non-blocking work and handoffs

| Consumer | Needs | Target | If late |
|---|---|---|---|
| registry-service | Shared envelope/event contract | P2 start | Use committed stub package. |
| incident manager | Anomaly event schema | P3 | Use test event producer. |
| RCA layer | Telemetry/deploy query APIs | P4 | Use seeded evidence fixtures. |
| console | OpenAPI/API responses | Per page phase | Continue on generated mock server. |
| remediation executors | Action catalog and policies | P5 | Use dry-run mode. |
| all workstreams | Shared Compose/infra stack | Available baseline | Keep local setup reproducible. |

**Handoff rule:** the provider commits the contract and a sample response/event; the consumer confirms it against a mock or test; the real implementation replaces the mock without changing the agreed shape silently.

---

## 5. End-of-phase integration routine

1. Freeze new feature work for the final 2–3 days; fix defects only.
2. Run the phase checkpoint from a clean environment and record evidence.
3. Review the gate checklist; record pass/fail and decisions in the planning log.
4. If a gate fails, record the gap and next check date; do not label the phase complete.

### Gate checklist

- [ ] Gate behavior demonstrated and acceptance targets checked.
- [ ] Integration checkpoint passed; evidence linked.
- [ ] Tests and CI pass where applicable.
- [ ] Contracts, diagrams, and planning docs updated as needed.
- [ ] Decisions and risks recorded in the decision log.

---

## 6. Autonomy and safety boundary

All remediation—including rollback—uses the same policy and execution path. The AI may gather evidence and recommend actions; it does not receive unrestricted write access. High-risk actions require approval, automatic actions must be predefined, low-risk, reversible, rate-limited, and auditable; recovery verification is required before closing an incident. See [features.md](features.md) A6–A9 and the autonomy ADRs.

---

## 7. Demo application: AegisShop

AegisShop is the project's instrumented retail microservices app, used as the target for telemetry, faults, and evaluation. It is not part of the AegisSRE control plane.

| Service | Responsibility | Stack | Example fault target |
|---|---|---|---|
| `shop-gateway` | Public API entry | FastAPI | HTTP 5xx, traffic spike, latency |
| `catalog-service` | Product catalogue | FastAPI | CPU saturation |
| `cart-service` | Shopping cart | FastAPI + Redis | Redis unavailable |
| `order-service` | Order processing | FastAPI + PostgreSQL | DB unavailable, faulty deployment |
| `payment-service` | Simulated payments | FastAPI | Container crash, latency |

All services emit metrics, logs, and traces. PostgreSQL supports orders; Redis supports cart. Any cross-service call must appear in `docs/contracts/` first (contract-first rule).
