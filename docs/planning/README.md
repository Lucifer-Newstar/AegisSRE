# Planning

> Home of the **scope, delivery sequence, and schedule** for AegisSRE. Each file has one job; use the links below to find the right level of detail. Decisions that change scope or interfaces are recorded in §2.

---

## 1. Start here

| If you need to know… | Read… |
|---|---|
| What is included and how it is accepted | [features.md](features.md) |
| What each development phase must deliver and demonstrate | [phases.md](phases.md) |
| When phases are targeted | [timeline.md](timeline.md) |
| How the finished console should look and behave | [product-vision.md](product-vision.md) |
| The short milestone summary | [project roadmap](../project/roadmap.md) |
| Cross-boundary integration risks and their decisions | [integration-edge-cases.md](integration-edge-cases.md) |

**Source of truth:** feature acceptance belongs in `features.md`; phase gates in `phases.md`; target dates in `timeline.md`. The roadmap summarizes those decisions and should not introduce new scope.

---

## 2. Decision Log

| Date | Decision | Decider | Recorded in |
|---|---|---|---|
| 2026-08-31 | Project objective confirmed (research question): AI-assisted SRE platform reducing MTTD/MTTR, accurate RCA, safe autonomous remediation. | Navin Jairam | [proposal.md](../project/proposal.md) |
| 2026-08-31 | Runway: **8–10 months** (started Aug 2026 → delivery window Apr–Jun 2027). | Navin Jairam | [timeline.md](timeline.md) |
| 2026-08-31 | **Scope locked:** All Tier A (core loop) + B1 RAG + B2 Ask Aegis + C1/C3/C4/C5 + D1/D5/D6 + E2/E4. Explicit cuts: B3, B4, B6, C2, C6, D2, D3, D4, E3, E5 (B3 = optional buffer stretch). | Navin Jairam | [features.md](features.md) |
| 2026-08-31 | **Demo subject:** build a **dedicated demo microservices application** (fully controlled faults) rather than adapting an existing one. | Navin Jairam | [features.md](features.md#2-approved-scope-at-a-glance) |
| 2026-08-31 | **Micro-decisions locked:** demo app named **AegisShop**; demo stack = Python/FastAPI + OTel + Postgres/Redis; B3 fine-tuning kept as gated buffer stretch; D1 cluster = **kind** (fallback k3s). | Navin Jairam | [phases.md](phases.md#7-demo-application-aegisshop) |
| 2026-08-31 | **Phase-gated development:** project split into phases P1–P8; each phase ends with a **ready-and-working increment** (gate) + integration checkpoint; workstreams designed to be **non-blocking** (contracts-first, mocks); moving on requires a gate review. | Navin Jairam | [phases.md](phases.md) |
| 2026-08-31 | **UML documentation set:** all 14 UML 2.5 diagram types, authored in **Mermaid** under `docs/architecture/uml/` (GitHub-rendered); Use Case split into platform + AegisShop files. | Navin Jairam | [docs/architecture/uml/](../architecture/uml/) |
| 2026-09-01 | **Deployment Intelligence tier:** added a first-class **DI tier** (DI-1…DI-7: deployment tracking, risk scoring, change-incident correlation, bad-rollout detection, rollback intelligence, canary analysis, change-failure analytics) integrated into existing phases P2–P8 (no timeline change). Full capability set chosen. (An earlier working title "AegisSRE" dates from this upgrade; the project name remains AegisSRE — see 2026-11-22 entry.) | Navin Jairam | [features.md](features.md) · [deployment-intelligence.md](../architecture/deployment-intelligence.md) |
| 2026-09-01 | **Walking-skeleton base layer (before P2 ramp):** build a lean shared foundation first — root tooling config; `backend/libs/telemetry` (envelope v0.2); `backend/libs/eventbus` (Redis Streams); `backend/services/_template` (FastAPI service template); one vertical slice `demoapp/aegisshop/catalog-service` (in-memory, OTLP → Grafana via compose); compose + CI wiring. A3–A9 explicitly deferred to P3–P5. Decisions: AegisShop lives in `demoapp/aegisshop/`; template is a copy-paste pattern (not the real gateway); slice = catalog-service. | Navin Jairam | [phases.md](phases.md) · [demoapp/](../../demoapp/) |
| 2026-09-01 | **Contracts-first executed (P2):** P2 OpenAPI contract set drafted in `docs/contracts/` (registry :8101, deployments/DI-1 :8701, AegisShop v1); event catalogue v1 added to telemetry-model.md §3.5 (incl. deployment state machine for DI-4); CORS dev policy (allow console origin in dev only); PR template with Definition-of-Done checklist; **integration edge-case register** opened; contract-drift CI check. Freeze 2026-09-08. | Navin Jairam | [contracts/](../contracts/) · [integration-edge-cases.md](integration-edge-cases.md) · [../../.github/pull_request_template.md](../../.github/pull_request_template.md) |
| 2026-09-08 | **P2 contracts freeze for implementation:** additive-only after this date; console host port is 3030 so Grafana can remain on 3000. | Navin Jairam | [contracts/](../contracts/) · [port-register.md](../architecture/port-register.md) |
| 2026-10-10 | **P2 MVP slice landed:** A2 registry, DI-1 deployments, AegisShop cart/order/payment, Grafana overview, Compose/K8s wiring, console scaffold on mocks. Gate review target 2026-10-31. | Navin Jairam | [contracts/](../contracts/) |
| 2026-11-22 | **Personal-project consolidation:** history and docs consolidated into this personal AegisSRE repository. Project name fixed as **AegisSRE** ("AegisDeploy" survives only in internal code/container identifiers). Team-era planning artifacts (member folders, sync packs, trackers) removed; docs rebuilt for a solo build. | Navin Jairam | this log |

*New decisions are appended; nothing is silently edited.*
