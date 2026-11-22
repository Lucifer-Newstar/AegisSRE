# Kubernetes deployment (K8s-ready posture)

Per **ADR-0005**, the platform is developed with Docker Compose but structured to be
Kubernetes-ready: every service has (or will have) a 1:1 Kustomize base in `base/`,
using the same image tags, environment variable names, and config mounts as Compose.

## Current state

- `base/kustomization.yaml` retains the application bases. The complete
  `../kustomization.yaml` assembly adds all current platform dependencies,
  runtime/gateway workloads and shared configuration generators.
- [The local-demo kind guide](../../docs/operations/kind-platform.md) lists all
  required Secrets, storage prerequisites and safety limits. A hosted owned-kind
  gate must demonstrate real startup/persistence before merge.
- CI validates the manifests and both Kustomize assemblies.
- Registry/deployment workloads require a namespace-local `aegissre-database`
  Secret with key `url` for `DATABASE_URL`. No actual database credentials are
  committed.
- Running on kind is distinct from real remediation, full live-console scope,
  chaos fault injection and measured evaluation. Those remain tracked separately
  in the [acceptance ledger](../../docs/implementation/status.md).
  Manifest validation alone is not a running-cluster claim.

## Conventions

- One manifest per workload/statefulset + matching Service.
- Config maps mount the exact files under `infra/` (same content as Compose mounts).
- Environment comes from env vars / secrets — never hardcoded endpoints
  (service discovery differs from Compose DNS).
- Overlays (e.g., `overlays/dev/`, `overlays/prod/`) add per-environment patches.

## Preview of mapping (as components land)

| Compose service | K8s resource |
|---|---|
| postgres | StatefulSet + Service `postgres` |
| redis | StatefulSet + Service `redis` |
| prometheus | Deployment/StatefulSet + Service `prometheus` |
| grafana | Deployment + Service `grafana` |
| loki | StatefulSet + Service `loki` |
| tempo | StatefulSet + Service `tempo` |
| otel-collector | Deployment + Service `otel-collector` |
