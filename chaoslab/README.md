# Isolated chaos CLI foundation

This first runner is deliberately restricted to the current newly owned
full-platform GitHub-runner kind fixture. It cannot use an ambient context,
existing cluster, arbitrary target, arbitrary namespace or caller command.
A current ownership marker, expected shop labels and unchanged workload UID
are required. An exclusive active-run marker prevents concurrent experiments;
failed runs retain that marker for investigation rather than silently allowing
another experiment over unresolved state.

From the repository root, inside that fixture:

```sh
python -m chaoslab http-5xx --seconds 5 --output /tmp/experiment-journals
```

Hook workloads must already have `AEGIS_SHOP_FAULTS_ENABLED=true` through the
owned fixture's setup. Normal Compose/Kustomize workloads do not enable hooks.
There is no HTTP control API. The hook file is local and bounded, expires within
ten minutes, and is removed on restoration. SIGTERM and normal exceptions enter
the restoration block. SIGKILL cannot run cleanup, which is why hooks expire and
the enclosing fixture's cluster cleanup remains required.

Supported runner operations so far:

| Operation | Actual effect | Acceptance limitation |
|---|---|---|
| `http-5xx` | catalog requests return 503 | one actual hosted CLI check required |
| `network-latency` | dependency application-boundary delay | not kernel packet shaping |
| `cpu-saturation` | bounded CPU work on requests | sustained saturation still requires measurement |
| `memory-pressure` | bounded live allocation | explicitly not memory exhaustion or OOM |
| `database-outage` | shop DB replicas 1 to 0, then back to 1 | controller restoration is not app-health recovery |
| `dependency-failure` | shop Redis replicas 1 to 0, then back to 1 | same health limitation |

The named fault primitives below remain subject to real hosted proof. Container crash and invalid configuration are implemented
below, with real hosted proof required. The final A11 ten-fault catalogue is not
complete. The current hook/runner set must not be reported as meeting it.

Each unique JSONL journal is created exclusively, flushed and fsynced on every
stage. It records preparation, mutation request, control application, failure,
and restoration result separately. Application of control is not independently
observed symptom onset. Restored replicas/control files are not independently
verified application recovery. No MTTD/MTTR, accuracy or autonomous success is
invented from these timestamps. Ground-truth labels stay in the journal and are
not injected as platform evidence or displayed in shop responses.

The full-kind gate must demonstrate real HTTP failure, independent liveness,
CLI completion, restored normal response and the journal stages. Other hooks
currently have native safety tests only. Full fault coverage, independent health
truth, split manifests, evaluation repetitions and research comparisons remain.

## Container process crash

`python -m chaoslab container-crash --seconds 5 --output PATH` sends fixed
SIGUSR1 to PID1 inside the current owned catalog-service container. The opt-in
startup handler then immediately exits with code70, without shutdown cleanup. This is necessary because Linux
PID namespace init ignores peer SIGKILL; no arbitrary signal is accepted. The
runner has no caller-selected command/PID/namespace/target. Kubernetes restart
is the restoration mechanism; a successful rollout wait is not proof of
business recovery. The kind gate independently requires the same Pod UID,
increased container restart count, last exit70 and restored `/products`200,
then saves that proof separately from the ground-truth journal. No real run is
claimed until this hosted gate passes. It is not OOM, node deletion, detection
accuracy or an A12 trial. Other missing faults/evaluation remain.

PID-namespace signal behavior: https://man7.org/linux/man-pages/man7/pid_namespaces.7.html

## Invalid configuration rollout

`config-error` changes the real bounded `CATALOG_MAX_PRODUCTS` setting to zero.
Pydantic rejects this out-of-range value when the new catalog process starts.
Restoration puts back the exact prior explicit environment entry (including
valueFrom) or removes it if absent, then waits for the Deployment rollout.
The rolling strategy can keep the previous healthy replica serving, so this
experiment claims a failed configuration rollout, not a guaranteed outage.
The owned-kind proof independently checks a failed new process, validation log,
non-ready container, exact Pod-template restoration and domain response. It is
not a fabricated HTTP failure switch or an evaluation accuracy result. Hosted
proof is required before merge; only local tests have passed so far.


## Actual memory exhaustion

`memory-exhaustion` is distinct from bounded `memory-pressure`. It requires
the owned catalog Deployment to have exactly the fixed 256Mi application
memory limit, then allocates and touches up to 384Mi in the request-serving
process. The runner does not remove the memory limit or alter host resources.
The actual hosted check must observe same-Pod restart and Kubernetes
`OOMKilled` reason with exit137, then a healthy business request. Allocation,
connection loss and runner completion alone are not OOM proof. The ephemeral
control file disappears on container restart and is explicitly removed at
restoration. No hosted OOM result or evaluation accuracy is claimed yet.


## Bounded traffic spike

`traffic-spike` runs eight threads with 100ms per-thread spacing and 2s
request timeouts against the fixed local `/products` endpoint inside the owned
catalog container. Duration is bounded to 1..120 seconds; no destination,
concurrency, endpoint or caller command is accepted. The child exits before
restoration, without changing workload configuration or leaving a daemon.
The hosted gate independently requires a Prometheus request-counter increase
of at least100 during a ten-second CLI trial and a subsequent200 response.
The counter includes background traffic and scrape timing; it is not an exact
RPS measurement, sustained load claim or detection-accuracy acceptance.
Hosted proof is pending.

## Faulty release

`faulty-deployment` replaces the fixed catalog container image with a separately
built defective revision. Its `/products` implementation returns503 while
liveness remains200; normal images have no setting to enable this defect.
The fixed faulty tag is built and loaded only in the newly owned fixture.
Restoration returns the exact previous image and waits for rollout. The hosted
gate must independently observe the actual faulty image/Pod,503 domain response,
200 liveness, exact restored Pod template and200 domain recovery. It does not
claim deployment-event collection, bad-rollout detection, automated policy
rollback or DI accuracy merely because the CLI restored the image.
Hosted acceptance is pending. All ten named primitives now have code paths,
but bounded CPU is not sustained saturation, and measurements/evaluation plus
hosted proof of the newly added operations remain required.
