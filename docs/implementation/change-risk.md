# Change-attribute risk baseline

Authenticated POST /deployment-intelligence/risk-preview freezes a proposed
identity/revision and caller-asserted change size, affected-service count and
owner experience. Source references remain caller assertions. Current service
checks come from actual prior health events, fresh within 60 seconds. UTC cyclic
time, size, blast radius, owner experience and health form the feature vector.
A fixed regularized logistic model trains on prior explicit, unambiguous,
confirmed outcomes with frozen pre-deploy attributes and health. At least20
outcomes and five examples per class are required. Truncated history, missing
attributes or missing/stale health produce unknown, not safe. No generated
training data, random train/test split or current/later labels are used.

A preview binds only to the same deployment identity/revision beginning within
60 seconds after it. Reused preview inputs are immutable. Later registration
gets a separately labelled post-registration assessment. Snapshots include
training records/digest and model version. Service empirical propensity remains
separate; neither score is an execution grant. This is a baseline, not calibrated
production risk, measured held-out recall or a claim of full DI-2 acceptance.

Tests exercise real sklearn fitting on explicit unit fixtures, chronological and
scope exclusions, insufficient inputs, frozen identity, and stale health. Unit
fixtures are not research results. The runtime gate checks preview API wiring
and persistent unknown snapshots through the real gateway and service stack.
