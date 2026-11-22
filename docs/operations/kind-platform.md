# Complete local-demo kind platform

`infra/kustomization.yaml` assembles all seventeen current Compose services in a
dedicated `aegissre-demo` namespace. The seven existing app bases remain usable
independently. The added platform resources include PostgreSQL/pgvector, Redis,
Prometheus, Grafana, Loki, Tempo, OpenTelemetry Collector, the reliability runtime
and gateway. This is a single-replica local demo, not a production deployment.

## Shared configuration and storage

The infra-root Kustomization mounts the same Prometheus rules, OTEL/Loki/Tempo
files and Grafana provisioning/dashboard files used by Compose. It does not copy
those configurations into another source of truth. Generated ConfigMap names
are hashed, so configuration changes update the affected Pod templates.

PostgreSQL, Redis, Prometheus, Grafana, Loki and Tempo each have a PVC. A dynamic
StorageClass is required. The normal kind storage provisioner supplies it in the
hosted fixture. Application restarts and Postgres Pod replacement must preserve
business records. Deleting PVCs, the namespace or the kind cluster destroys its
data. Do not use these commands on an existing cluster containing user data.

## Credentials are prerequisites, not committed values

First create a **new** disposable kind cluster and load all nine application
images built by `docker compose build`. Use the kind/kubectl versions and node
image in [reviewable pins](../../infra/kind/ci-versions.json). Never select an
ambient production context. All examples below require the explicitly selected
context for that new cluster.

Create namespace-local Secrets from private environment files. Choose actual
unique values with a password manager. Do not commit the files or send their
contents in chat. The database URL must match the Postgres values and address
`postgres:5432`. Required file keys:

| Secret | Required keys |
|---|---|
| `aegisshop-postgres` | `username`, `password`, `database`, separate from platform credentials |
| `aegisshop-database` | `url`, a `postgresql+psycopg` URL pointing to `shop-postgres:5432` |
| `aegissre-postgres` | `username`, `password`, `database` |
| `aegissre-database` | `url`, a `postgresql+psycopg` URL |
| `aegissre-metadata` | `api-token`, `read-token`, distinct from each other |
| `aegissre-operator` | `token`, `incidents-token` |
| `aegissre-grafana` | `username`, `password` |

The metadata operator token must also differ from gateway/incidents credentials.
The collector/indexer receive only the metadata read key. The gateway replaces
caller credentials with its configured upstream keys. Probe commands read keys
from Pod environment, not committed HTTP-header values.

After setting `CONTEXT` to the new cluster's context and preparing those private
files, create the namespace, create each named Secret with `kubectl --context
"$CONTEXT" --namespace aegissre-demo create secret generic NAME
--from-env-file=PRIVATE_FILE`, then apply:

```sh
kubectl --context "$CONTEXT" create namespace aegissre-demo
# Create the seven required Secrets in that namespace before applying workloads.
kubectl --context "$CONTEXT" apply -k infra
kubectl --context "$CONTEXT" -n aegissre-demo get pods,pvc
kubectl --context "$CONTEXT" -n aegissre-demo rollout status deployment/api-gateway
kubectl --context "$CONTEXT" -n aegissre-demo port-forward --address 127.0.0.1 service/api-gateway 8080:8000
```

The CI fixture uses plainly labelled disposable test credentials instead. They
are not deployment defaults and must never be reused outside that fixture.

## Evidence permissions and execution boundary

Only the reliability Pod mounts a Kubernetes service-account credential. Its
`aegissre-evidence` Role permits namespaced list operations for Pods, Deployments,
ReplicaSets and `events.k8s.io` events. It cannot read Secrets, exec into Pods,
change workloads or read another namespace. Collection verifies the projected CA
and token. The bundled kind API certificate supports the configured service DNS
name; other clusters must use a name covered by their certificate.

The executor is fixed to simulation and the LLM provider is disabled. Bringing
up this stack enables neither real remediation nor model inference. Most
application Pods do not need a Kubernetes token and explicitly disable mounting
one. Runtime/gateway images run non-root with read-only roots and bounded scratch
space. Persistent stores run under explicit non-root IDs with volume group
ownership.

Services are ClusterIP-only and host access is via explicit loopback forwards.
That is not a network-isolation claim: Redis and observability backends retain
their Compose demo authentication posture, and no CNI enforcement is assumed.
Keep unrelated workloads out of this namespace and do not expose it to the
internet. Production tenancy, TLS between every service and database role
separation need separate deployment hardening.

## Actual hosted gate and its limits

The `Full platform (owned kind + persistent stores)` CI job runs
[its bounded driver](../../scripts/ci/kind_platform_gate.py). It refuses a
pre-existing named cluster, uses a separate kubeconfig and explicit context on
every kubectl call, and deletes a cluster only with this run/attempt/job's owner
marker. It builds all application images, loads them into kind, creates only
fixture credentials and applies the complete Kustomization.

The gate requires all seventeen workloads to roll out, then reuses the running
HTTP/SQL/Redis proofs for real Prometheus collection, OTLP log/trace joins,
pgvector retrieval, read-only Ask, deployment-window results and restart recovery.
Synthetic source history stays labelled as synthetic. It checks actual
projected-SA/TLS collection and denied mutation/Secret permissions, replaces the
Postgres Pod without deleting its PVC, and requires the same metadata record to
remain readable. It also checks the current console responds, not that its
unfinished eight-page live-data scope is complete.

Local schema/static tests do not establish these results. The hosted gate must
pass on the exact PR head before merge. Even a passing gate is not ten real
faults, safe autonomous recovery, model quality, or measured MTTD/MTTR acceptance.
Those remain in the [acceptance ledger](../implementation/status.md).

This repository uses standard `ubuntu-latest` runners in a public repository.
[GitHub's current billing policy](https://docs.github.com/en/actions/concepts/billing-and-usage)
states standard public-repository runner usage is free. This fixture creates no
paid cloud resources or model calls and publishes no container images. Recheck
costs before using private repositories, paid runners or cloud infrastructure.

## Isolated shop order database

The seventeenth workload, `shop-postgres`, has its own StatefulSet, service,
credentials and `shop-postgres-data` PVC. Order-service uses `SHOP_DATABASE_URL`
from `aegisshop-database`, never the platform evidence database. No host port is
published for this shop database in Compose. Do not reuse platform credentials
when creating the two shop Secrets.

`/health` reports process liveness; `/ready` checks the order database. Order
reads/writes and readiness return 503 during a database outage. Cart transport
failure also returns 503 rather than pretending the cart is empty. Schema
creation is lazy so an unavailable dependency does not prevent the process from
starting. After reconnection, the same committed order is readable. There is no
automatic clearing/reseeding or transient in-memory write fallback.

The full-platform CI gate must also prove a real order survives an application
restart, scale only its newly owned `shop-postgres` to zero, observe domain and
readiness 503 while liveness/platform APIs remain up, restore the StatefulSet in
a `finally` block, and read the unchanged order. This is one integration proof,
not the A11 CLI, ten-fault coverage, recovery acceptance or an evaluation result.
The cart still uses the prior in-memory implementation; Redis-backed carts are
remaining work, not implied by the order database change.
