# Project Timeline

> **Purpose:** dates, phase overlap, and focus per period. Use [phases.md](phases.md) for gates and [features.md](features.md) for feature scope and acceptance criteria. The plan covers Aug 2026–Jun 2027; dates are targets, gates determine completion.

---

## 1. Calendar at a glance

| Stage | Target window | Main work | Checkpoint |
|---|---|---|---|
| P1 · Foundation | Aug–Sep 2026 | Repo, docs, ADRs, shared stack, CI | Passed 2026-08-31. |
| P2 · Observability + AegisShop v1 | Sep–Oct 2026 | A1/A2, app v1, DI-1, console scaffold | Telemetry, registry, deploy history, and scaffold work together. MVP slice landed 2026-10-10. |
| P3 · Detection + incidents | Oct–Nov 2026 | A3/A4, DI-4 base | Fault → anomaly → incident. |
| P4 · AI reasoning | Nov–Dec 2026 | A5/B1/B2, DI-2/DI-3 | Evidence-cited reasoning and deploy correlation. |
| P5 · Remediation + autonomy | Dec 2026–Jan 2027 | A6–A9, DI-5 | Approval and safe-auto recovery loop. |
| P6 · Product completion (parallel) | Nov 2026–Jan 2027 | C1/C3–C5, D5/D6, DI-7 dashboard | Eight-page live-data walkthrough. Runs alongside P5. |
| P7 · Kubernetes + chaos lab | Jan–Feb 2027 | D1/A11, DI-6 | Cluster and fault-injection demo. |
| P8 · Evaluation + report | Feb–Mar 2027 | A12/E2, DI-7 results | Reproducible report. |
| Report + demo | Mar–Apr 2027 | Report, video, final polish | Submission-ready package. |
| Buffer | Apr–Jun 2027 | Hardening; B3 only if approved | Demo-ready. |

## 2. Focus by period

| Period | Focus |
|---|---|
| **Sep–Oct** | Shared telemetry/event contracts; A1 observability + Compose wiring; A2 registry/health; AegisShop backend; DI-1 API; console scaffold on mocks |
| **Oct–Nov** | A3 detection and DI-4 evaluation; metric plumbing and fault validation; A4 incident manager; service/incident console views |
| **Nov–Dec** | A5, B1, B2, DI-2, DI-3; read-only query proxies; evidence and deploy-history APIs; incident reasoning panel; Ask Aegis UI |
| **Dec–Jan** | A6/A8/A9 policy, safety, verification; DI-5; scoped executors including rollback; approval UI and autonomy indicator |
| **Nov–Jan (parallel P6)** | SLO definitions; D5/D6; DI-7 dashboards; API polish/client generation; remaining console pages (deployments, runbooks, postmortem, audit) |
| **Jan–Feb** | A11 experiment specs and ground truth; D1, chaoslab, DI-6 canary analysis; fault hooks and app hardening; cluster UX check |
| **Feb–Mar** | A12, E2, CFR analysis; stable evaluation cluster; finalize API docs; demo video/screenshots |
| **Mar–Jun** | Report results, optional approved B3, final demo polish |

## 3. Target gate dates

| Gate | Target date | Completion evidence |
|---|---:|---|
| P1 | 2026-08-31 | Passed. |
| P2 | 2026-10-31 | P2 checkpoint in [phases.md](phases.md). |
| P3 | 2026-11-30 | P3 checkpoint. |
| P4 | 2026-12-31 | P4 checkpoint. |
| P5 | 2027-01-31 | P5 checkpoint. |
| P6 | 2027-01-31 | Eight pages and operational panels live. |
| P7 | 2027-02-28 | Cluster + chaos checkpoint. |
| P8 | 2027-03-31 | Evaluation report committed. |
| Report + demo | 2027-04-30 | Final materials ready. |
| Buffer | May–Jun 2027 | Demo-ready. |

## 4. Working cadence

- **Phase-end integration:** run the checkpoint from a clean environment and review the gate before starting the next phase.
- **Documentation:** update the relevant feature file and decision record when scope or an interface changes, in the same commit as the change.

## 5. Schedule risks

| Risk | Response |
|---|---|
| A phase gate slips | Reduce to the smallest working slice; move optional work out; record the revised target in the decision log. |
| Model/hardware limits | Keep RAG model-independent; use a rule-based fallback for the demo; B3 remains optional. |
| API integration delays | Use the agreed OpenAPI contract and mocks until the provider implementation lands. |
| Scope grows | Do not add cut items informally; require a decision-log entry. |
| Evaluation results are weak | Validate faults and protocol early; retain raw runs and report limitations honestly. |
