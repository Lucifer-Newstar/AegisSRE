# Retained-template rollback

The Kubernetes rollback executor selects one retained ReplicaSet by exact
Deployment owner UID, namespace and numeric revision. It restores only that
workload template, removing controller-generated pod-template-hash. A JSON
patch tests current Deployment UID and resourceVersion before replacing the
template. Concurrent deployment changes fail instead of racing a blind undo.
The existing allowlist, managed label and one/two revision distance still apply.
Automatic calls still require expected UID and a fresh dispatch callback.

Unit checks cover exact patch preconditions and ownership rejection. The owned
cluster gate deploys the real faulty image, verifies503, uses the scoped executor
to restore the retained revision, verifies200 and exact original template, and
restores the label. This is an explicit seeded executor test, not end-to-end
inferred DI-5, automatic authorization, or measured80% recovery acceptance.
Rollback remains high-risk and approval-required by the shipped default policy.
