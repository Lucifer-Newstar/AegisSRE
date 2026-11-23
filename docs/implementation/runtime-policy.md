# Runtime policy changes

Authenticated `GET /api/v1/policy` reads the current policy. To change it, put the
system in observe mode and POST a complete policy, its `expected_version`, and an
actor. The gateway replaces the supplied actor with its authenticated principal.
A new version is required. Previously used versions cannot be rewritten. A stale
expected version returns409, as does an active reserved execution.

The policy and immutable version records commit with the audit entry. The policy
survives application restarts and is read from durable state by every worker,
not cached in one process. Existing plans do not override a newly forbidden rule.
Observe mode remains on until the operator deliberately changes it. No model tool
can update policy. The existing hard action bounds remain independent of policy.

An initial file remains a bootstrap default only before the first durable update.
The final automatic-dispatch callback compares the current policy with the reserved
policy. A request already accepted by Kubernetes cannot be recalled by a policy
change or kill switch. The owned cluster gate updates through the gateway, checks
the asserted actor, restarts the API and verifies policy/mode persistence. Native
regressions check CAS, immutable versions, observe-only updates, in-flight refusal,
reopening and a newly forbidden rule across separate worker instances. These are
policy-control proofs, not the complete fault safety/accuracy evaluation.
