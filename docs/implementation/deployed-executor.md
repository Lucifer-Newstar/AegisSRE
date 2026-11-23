# Opt-in deployed executor for controlled evaluation

The base stays in simulation. `scripts/enable_scoped_executor.py` is an explicit
opt-in for a newly owned local/CI fixture only. It first puts durable autonomy in
observe mode, then adds a separate execution service account, narrow Role and
projected short-lived token kubeconfig. It does not approve or execute any plan,
relax policy, turn on safe-auto or label workloads managed. The evidence-reader
account receives no new write permissions.

The executor can get/patch only the four named demo Deployments and get/update/
patch their scale subresources. ReplicaSet listing remains namespace-wide because
retained revision ownership must be resolved by UID. It can read the existing
namespace evidence Role. It cannot read Secrets, create exec sessions, delete
Pods or patch the platform API. Kubernetes RBAC cannot constrain patch content;
application policy, target labels and UID/revision/template/CAS guards remain
necessary. This is a disposable demonstration identity, not multi-tenant isolation.

`check_deployed_executor.py` tests the actual deployed backend, not an independent
native executor. It checks denied permissions, inserts an explicitly labelled
integration plan directly into the fixture database, approves through the gateway,
then calls the API's executor. It expects real one-to-two scale, the authenticated
actor and a durable Kubernetes undo. Cleanup returns to observe and restores one
replica. It does not pretend the plan was inferred, that recovery was verified,
or that it measured autonomous success. Actual evidence must come from CI before
this path is called proven.

For Windows/WSL2, do not enable the path until the basic local smoke is healthy.
Run only against the explicit local-owned fixture:

```sh
export AEGIS_LOCAL_EVALUATION=1
python scripts/enable_scoped_executor.py
```

This enables real write capability but leaves observe blocking execution. The
manual/Aegis trial protocol must separately select mode, authorize actions,
record independent outcome evidence and distinguish safety cleanup from real
remediation. Existing timer-based chaos smoke is not a fair MTTR comparator.
