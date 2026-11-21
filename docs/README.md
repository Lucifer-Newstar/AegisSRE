# AegisSRE — Documentation

> **The navigation hub for all project documentation.**
> If you are looking for *anything* about AegisSRE, start here.
>
> Maintainer: Navin Jairam. Updated whenever the structure changes.

---

## 1. Document Tree

```text
docs/
├── README.md                    ← you are here (index & reading order)
│
├── project/                     ← WHAT & WHY (the big picture)
│   ├── proposal.md              ← the original project proposal (full text)
│   └── roadmap.md               ← milestone-level roadmap
│
├── contracts/                   ← API contracts (OpenAPI, freeze 2026-09-08)
│   ├── README.md                ← conventions + mock-server + CORS + drift guard
│   ├── manifest.json            ← service → contract mapping (drift check)
│   ├── registry-service.yaml    ← A2 registry + health (:8101)
│   ├── deployments-service.yaml ← DI-1 deploy tracker (:8701)
│   ├── catalog-service.yaml     ← catalog (:9001, LIVE slice)
│   ├── cart-service.yaml        ← cart (:9002)
│   ├── order-service.yaml       ← order (:9003)
│   └── payment-service.yaml     ← payment (:9004)
│
├── planning/                    ← SCOPE & SEQUENCE (development-phase planning)
│   ├── README.md                ← planning index + decision log
│   ├── features.md              ← locked feature scope (A1–A12, B, C, D, E, DI)
│   ├── product-vision.md        ← how the final product looks & behaves
│   ├── phases.md                ← phase plan: gates, non-disruption and integration
│   ├── timeline.md              ← 8–10 month calendar
│   └── integration-edge-cases.md← cross-boundary risk register
│
├── architecture/                ← SYSTEM DESIGN (how the platform works)
│   ├── system-architecture.md   ← components, responsibilities, data flows
│   ├── port-register.md         ← services, ports, DNS, metric/label rules
│   ├── deployment-intelligence.md ← DI tier: deployment risk, correlation, rollback, CFR
│   ├── autonomy-model.md        ← Levels 1–5 autonomy, policy engine, safety
│   ├── telemetry-model.md       ← unified telemetry/event envelope contract
│   ├── uml/                     ← the 14-diagram UML set (Mermaid, GitHub-rendered)
│   └── adr/                     ← Architecture Decision Records (ADRs)
│
├── development/                 ← HOW TO BUILD (engineering conventions)
│   ├── contributing.md          ← workflow + conventions + Definition of Done
│   ├── local-setup.md           ← one-time machine setup + env variable reference
│   └── tech-stack.md            ← selected technology stack & rationale
│
└── operations/                  ← HOW TO RUN & MEASURE
    └── evaluation.md            ← SRE/ML/automation metrics & protocol
```

## 2. Index by Topic

| Topic | Go to |
|---|---|
| What is this project? | [project/proposal.md](project/proposal.md) |
| What is being built? (locked scope) | [planning/features.md](planning/features.md) |
| What does the final product look like? | [planning/product-vision.md](planning/product-vision.md) |
| What are the phases & gates? | [planning/phases.md](planning/phases.md) |
| What is the schedule? | [planning/timeline.md](planning/timeline.md) |
| How the platform works | [architecture/system-architecture.md](architecture/system-architecture.md) |
| How autonomy/remediation works | [architecture/autonomy-model.md](architecture/autonomy-model.md) |
| The telemetry/event contract | [architecture/telemetry-model.md](architecture/telemetry-model.md) |
| Deployment Intelligence design | [architecture/deployment-intelligence.md](architecture/deployment-intelligence.md) |
| API contracts (OpenAPI) | [contracts/](contracts/) |
| Why this stack | [development/tech-stack.md](development/tech-stack.md) |
| Conventions & Definition of Done | [development/contributing.md](development/contributing.md) |
| Machine setup + env vars | [development/local-setup.md](development/local-setup.md) |
| How success is evaluated | [operations/evaluation.md](operations/evaluation.md) |
| Decision history | [planning/README.md](planning/README.md) §2 · [architecture/adr/](architecture/adr/) |

## 3. Reading Order

1. **Start here** — get the map.
2. **planning/features.md** — the locked scope (read before writing code).
3. **planning/phases.md + timeline.md** — when things happen and what "done" means per phase.
4. **architecture/** — how the system is designed (read before touching interfaces).
5. **contracts/** — the API contracts every service obeys.
6. **development/** — stack + conventions before the first commit.
7. **operations/** — how the whole thing will be judged.

## 4. Housekeeping Rules

- **One purpose per file** — every document answers one question; new topics get a new
  file in the right folder.
- **No orphans** — every file is reachable from this index; when you add a file, add its
  row to §2.
- **Living documents** — planning docs evolve; changes are logged in the decision log
  (planning/README.md §2), never silently.
- **ADRs for architecture** — interface/stack changes require an ADR
  (see [development/contributing.md](development/contributing.md)).
- **Honest status** — docs that describe unbuilt design say so; only the phase plan
  and roadmap claim what is proven.
- **Path discipline** — links inside docs use relative paths; repo-root paths are
  written as `docs/<folder>/...` in code comments/README.
