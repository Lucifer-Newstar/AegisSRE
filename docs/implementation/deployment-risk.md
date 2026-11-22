# Frozen empirical deployment risk

A new deployment registration freezes a versioned Beta-Binomial service-level
failure-propensity estimate using prior confirmed, explicit, unambiguous outcomes
whose assessment preceded this deployment. Unknown or legacy untimed assessments
are excluded, not treated as healthy. With fewer than10 eligible outcomes, the
score is unknown. A truncated training view is also insufficient. Model version,
fixed prior, source IDs and training digest travel with the snapshot.

The model is intentionally a baseline, not a change-attribute classifier or a
validated prediction. It does not invent diff size, migration flags, ownership,
training labels or held-out recall. A late registration is labelled post-deploy,
not passed off as a pre-deployment prediction. The API returns the frozen snapshot
without retraining from later failures. Observed post-rollout outcome is separate.
Legacy rows have no invented snapshot. The console shows these distinctions.

The score cannot authorize execution. Rollback stays fail-closed pending complete
live revision/rollout/risk integration and independently measured safety. Full
DI-2 acceptance, including faulty-deploy recall, is still outstanding.
