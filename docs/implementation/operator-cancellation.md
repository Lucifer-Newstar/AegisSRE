# Operator cancellation and bounded scale undo

Authenticated cancellation records an append-only request and blocks new automatic
work and automatic recovery closure. A queued action escalates immediately. A
reserved action checks cancellation before dispatch and during the automatic
executor callback. If the request overlaps a submitted command, its result/undo
record is retained and the incident escalates for reconciliation. Cancellation
cannot recall a command already accepted by Kubernetes and does not claim recovery.

Completed reversible scale actions have an explicit operator-only undo. The engine
reserves one attempt durably before external I/O; failures/uncertain attempts are
not silently retried. Kubernetes undo requires the same workload UID, namespace,
managed label, unchanged Pod template and exact applied replica count. A JSON patch
tests UID and resourceVersion before restoring the prior count. Other action types,
old incomplete records and changed targets require manual review, never blind
rollout-undo. The incident remains escalated after undo, not marked recovered.

The console forms enforce same origin, bounded input and session CSRF. The gateway
asserts the operator identity. Native tests cover cancellation before/during dispatch,
retained uncertain results, one-attempt reservation and changed live preconditions.
The owned scale proof additionally cancels and calls the actual guarded undo, checks
the restored replica count and preserves an escalation rather than a false closure.
This is scoped executor proof, not the full repeated autonomy safety benchmark.
