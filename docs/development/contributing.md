# Contributing

> Conventions for building AegisSRE. New here? Follow the
> [docs reading order](../README.md#3-reading-order) first.

## Workflow Summary

1. **Branches** — work on `feat/<area>-<topic>`; merge to `main`.
   `main` is always deployable.
2. **Commits** — Conventional Commits with scopes
   (`feat(backend): ...`, `docs(architecture): ...`).
3. **Quality** — small, reviewable changes; CI must pass; architecture changes
   need an ADR.
4. **ADRs** — any architectural or tech-stack decision requires an ADR in
   `docs/architecture/adr/` (copy `adr-template.md`).

## Conventions

- **Python (backend, ml, ai):** 3.12, `ruff` + `mypy --strict`, type hints required,
  Pydantic models for all schemas.
- **TypeScript (frontend):** strict mode, `prettier` + `eslint`.
- **YAML (infra, ci):** 2-space indent, explicit image tags/versions in Compose and K8s
  manifests; every Compose service has a healthcheck.
- **Secrets:** never commit; use `.env` locally (see `.env.example`), secrets managers in K8s.
- **Telemetry:** all events conform to the envelope in
  `docs/architecture/telemetry-model.md` — no bespoke event shapes.
- **Contracts:** any cross-service call appears in `docs/contracts/` first
  (contract-first rule).
- **Docs:** every change that affects docs updates the right sub-folder and the
  [docs index](../README.md) if the structure changed.

## Definition of Done

- Behavior demonstrated against the feature's acceptance criteria
  ([planning/features.md](../planning/features.md)).
- Tests added/updated; `pytest`, `ruff`, and `mypy --strict` pass; CI green.
- Contracts, envelope catalogue, port register, and K8s/Compose parity updated
  in the same change when affected (see
  [integration-edge-cases.md](../planning/integration-edge-cases.md)).
- Decisions that change scope or interfaces recorded in the
  [decision log](../planning/README.md).
