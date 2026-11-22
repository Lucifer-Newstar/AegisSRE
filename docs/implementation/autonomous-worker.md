# Policy-driven automatic worker

The durable runtime checks fresh pending incidents after event delivery. It will
not run an approved manual action on the operator's behalf. Only auto-safe mode,
a low-risk reversible plan and a matching versioned policy can authorize automatic
work. Missing collection evidence blocks the sweep. Each candidate is checked
again under the database transaction lock for mode, target, rate limit, cooldown,
state and plan age. A denied candidate does not flood the audit on every poll.

Automatic scale reads replicas from a managed, observed Kubernetes Deployment.
The executor reads again, refuses scale-down or a jump larger than one replica,
and submits a current-replicas precondition. Simulation does not invent live
replicas. The default policy still requires operator approval. Auto rollback
remains fail-closed because complete live risk and rollout preconditions are not
yet wired. Neither this worker nor a configurable policy establishes evaluation
accuracy or a production safety guarantee.

The kill switch is checked while reserving the action and again immediately
before dispatch. It cannot undo a command already accepted by Kubernetes. An
interrupted/uncertain action is escalated rather than blindly retried. Recovery
still requires the existing fresh health and affected-series evidence.

`check_autonomy_cluster.py` adds an explicit seeded low-risk scale fixture to the
owned disposable kind job. It checks recommend/observe blocks, one actual scale,
no duplicate action, persisted automatic actor and exact replica restoration.
It does not call this a detected fault or an evaluation success-rate sample.

The packaged image includes checksum-pinned kubectl. Actual Kubernetes execution
still requires an explicit mounted kubeconfig/context and separate scoped executor
credentials. The evidence reader is read-only and never receives deployment patch
permission. No default manifests enable execution or auto-safe mode.

CPU/load hypotheses can propose a bounded scale-up. Plan replicas are filled only
from a live managed Deployment read. Missing live context changes the plan to
operator escalation, not a guessed replica count. The versioned policy remains
the authority for risk/approval, and dispatch rechecks current replicas again.
