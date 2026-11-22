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

Crash, actual OOM, configuration error, faulty deployment and traffic-spike
experiments remain unimplemented. The final A11 ten-fault catalogue is not
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

`python -m chaoslab container-crash --seconds 5 --output PATH` sends a fixed
SIGKILL to PID1 only inside the current owned catalog-service container. The
runner has no caller-selected command/PID/namespace/target. Kubernetes restart
is the restoration mechanism; a successful rollout wait is not proof of
business recovery. The kind gate independently requires the same Pod UID,
increased container restart count, last exit137 and restored `/products`200,
then saves that proof separately from the ground-truth journal. No real run is
claimed until this hosted gate passes. It is not OOM, node deletion, detection
accuracy or an A12 trial. Other missing faults/evaluation remain.
