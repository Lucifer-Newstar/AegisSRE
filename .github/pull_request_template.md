# Pull Request Checklist (AegisSRE)

> Every change into `main` must satisfy the Definition of Done
> ([contributing.md](docs/development/contributing.md)).
> CI enforces what it can; the rest is reviewed before merge.

## Title & branch

- [ ] Conventional Commit: `feat|fix|docs|chore(<scope>): <summary>` (scopes: backend, frontend, ml, ai, chaoslab, demoapp, infra, ci, meta, docs(architecture|planning|adr))
- [ ] Branch: `feat/<area>-<topic>`

## Quality gates (must be green)

- [ ] CI: `yaml-and-compose`, `k8s-lint`, `docs`, `python-quality`
- [ ] Tests added/updated for new behavior (pytest)
- [ ] `ruff check backend demoapp` and `mypy` (strict) clean

## Contracts & conventions

- [ ] Uses the shared libs (`telemetry`, `eventbus`) — **no bespoke event shapes**
- [ ] New event type? → **event catalogue updated** (`docs/architecture/telemetry-model.md` §3.5)
- [ ] New/changed API? → **OpenAPI contract in `docs/contracts/`** (contract-first; freeze exceptions only via recorded contract change)
- [ ] New service? → **row added to `docs/contracts/manifest.json`** (drift check)
- [ ] Envelope changes? → additive-only; defaults for new fields
- [ ] Env vars via `config.py` + compose/K8s **parity** (ADR-0005) — same names in both runtimes
- [ ] New service? → compose service + Kustomize base + `python-quality` CI entry + **port register** updated

## Docs & demo

- [ ] Planning docs / integration edge-case register updated if behavior changed
- [ ] Decision log entry if scope or an interface changed
