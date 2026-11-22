# Observed live rollback policy context

The automatic worker can evaluate a rollback only when current Kubernetes revision
matches the explicitly identified, unambiguous bad window linked to this incident.
The target must be one unique earlier observed-healthy rollout, assessed before
the bad rollout began, with an existing scored risk snapshot. Missing data denies
automatic execution. Plans do not accept image tags or Git SHAs as Kubernetes
revision numbers.

Live preflight verifies managed UID, observed generation, one-replica workload,
a retained target one/two revisions away, and an image-only template change.
Any env/config/volume/probe/init-container difference requires approval.
At dispatch the current revision, target-template digest, UID, resource version,
mode and reserved incident plan are rechecked. Existing age, risk, cooldown,
rate and per-incident limits apply. The shipped policy remains high-risk and
approval-required: an operator must explicitly configure low-risk reversible
auto rollback before this route can be used.

The cluster proof uses deliberately seeded rollout/risk/incident prerequisites,
then real faulty image traffic and the real automatic worker/executor. It checks
observe/recommend do not run, auto-safe restores exact original template and
HTTP200 from503. It is not a diagnosis experiment or DI-5 acceptance statistic.
Unit tests cover context gaps, scope, ambiguous identity, config changes and
current-revision changes. Full repeated faults and80% recovery acceptance remain.
