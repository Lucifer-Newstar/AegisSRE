# Read-only Kubernetes evidence

The optional reader collects `events.k8s.io/v1` events for allowlisted demo
workloads. It is disabled by default and is separate from the write executor.
Enabling this reader does not enable Kubernetes remediation.

## Configuration

Run the reliability service in the chosen dedicated namespace with its own
service account and projected token/CA. Set:

| Setting | Default | Purpose |
|---|---|---|
| `AEGIS_KUBE_EVIDENCE_ENABLED` | `false` | Explicitly enable reads. |
| `AEGIS_KUBE_API_URL` | empty | Explicit HTTPS API origin, with no credentials, path, query or fragment. Use a hostname/IP covered by the API server certificate. |
| `AEGIS_KUBE_NAMESPACE` | `aegissre-demo` | One namespace, validated as a DNS label. |
| `AEGIS_KUBE_TOKEN_PATH` | `/var/run/secrets/kubernetes.io/serviceaccount/token` | Projected credential file. Its value is never a chat input or committed configuration. |
| `AEGIS_KUBE_CA_PATH` | `/var/run/secrets/kubernetes.io/serviceaccount/ca.crt` | Certificate bundle used for TLS verification. No insecure-TLS fallback. |
| `AEGIS_KUBE_POLL_SECONDS` | `30` | Read cadence, 15 to 300 seconds. |

Non-dev mode and an API bearer token are required. The durable delivery worker
must also be enabled and connected to Redis and the
business database. Credentials are reread for each request, so normal projected
token rotation does not require copying a token into an environment variable.
The reader does not inspect kubeconfig, run kubectl or use the executor context.
The API certificate is not guaranteed to cover `kubernetes.default.svc`; choose
the address covered by the control plane certificate rather than disabling TLS.

The [service account](../../infra/k8s/examples/evidence-reader-serviceaccount.yaml),
[Role](../../infra/k8s/examples/evidence-reader-role.yaml) and
[RoleBinding](../../infra/k8s/examples/evidence-reader-rolebinding.yaml) are
reviewable examples, deliberately not included in the base deployment. They
assume the dedicated namespace already exists and require the Pod to select
`serviceAccountName: aegis-evidence-reader`. They have only `list` permissions
for namespaced Pods, Deployments, ReplicaSets and events. There is no Secret,
exec, workload-write or cluster-wide permission, and the default service account
receives no grant. Do not reuse this account for an executor.

RBAC permissions cover those resource types throughout the namespace, not just
objects matching application labels. The application filters workloads by
`app.kubernetes.io/part-of=aegisshop` and an allowlisted
`app.kubernetes.io/name`; these filters are not an RBAC tenancy boundary. Keep
the demo namespace separate from unrelated private workloads. Full resource
responses are transient; only selected event fields and verified UID/service
relationships are retained, never Pod specs or environment values.

## Collection and attribution

Four bounded HTTPS list calls collect Deployments, ReplicaSets, Pods and events.
Workload ownership uses controller UID references from Deployment to ReplicaSet
to Pod. A matching Pod name alone cannot attribute an event: a recreated Pod has
a different UID. Event namespace and regarding-object namespace must both match.
Records store the API source, selected reason/message, regarding-object UID,
observed time and aggregate count. `series.lastObservedTime` takes precedence
over first occurrence time, so repeated event series preserve their observation
time rather than being stamped as newly observed on every poll.

The reader caps each response at 1MB and each resource list at 100 items. A
continuation token is reported as an incomplete-list failure, not silently
accepted as a complete scan. Redirects, compressed responses, malformed lists,
wrong namespaces, invalid credentials and oversized data fail closed. Network collection
has a ten-second deadline. Throttling or access denial stops the background
reader until operator intervention/restart rather than repeatedly hitting the
account.

Network reads run in a separate background task, not the fast delivery tick.
Validated events are staged through the existing SQL outbox and Redis delivery.
`/runtime` shows read errors, last successful read, emitted/ignored counts and
an explicit unknown health verdict. When enabled, stale/unavailable Kubernetes
reads make `/ready` fail. Missing events do not prove a healthy workload.

## Limits and validation state

Kubernetes events are best-effort supplemental evidence with limited retention;
the existence, timing and wording of a reason are not a stable causal guarantee.
Deleted objects absent from the current ownership snapshot cannot be attributed
and are counted as ignored. This is not a complete cluster audit or a watch-based
history. Messages are untrusted data and cannot grant permission for an action.

Native tests use explicit HTTP mock transports and a fake delivery worker for
background wiring. They cover UID ownership, namespace bounds, rotated token
reads, pagination/refusal, response limits, failure visibility, auth and readiness.
They do not prove a live Kubernetes connection or the full kind/fault acceptance
suite. No existing cluster was contacted to validate this feature. Actual kind
and least-privilege behavior checks remain acceptance work.

Sources checked for the protocol and permission model:

- [Kubernetes events API](https://kubernetes.io/docs/reference/kubernetes-api/events/event-v1/)
- [Accessing the API from a Pod](https://kubernetes.io/docs/tasks/run-application/access-api-from-pod/)
- [ReplicaSet API](https://kubernetes.io/docs/reference/kubernetes-api/apps/replica-set-v1/)
- [Deployment API](https://kubernetes.io/docs/reference/kubernetes-api/apps/deployment-v1/)
- [RBAC](https://kubernetes.io/docs/reference/access-authn-authz/rbac/)
