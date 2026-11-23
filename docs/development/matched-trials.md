# Matched local sessions and outcome review

This command runs one real bounded workflow, not the whole cohort. It does not
supply a human, invent a diagnosis, approve a plan or award recovery. Run one
local smoke first. No laptop session or benchmark result is included in the repo.

## Freeze, order and run

Use the [Windows/WSL2 owned fixture](windows-local-trials.md), with fault hooks
already enabled. Before an Aegis workflow, opt into the separately scoped deployed
executor with `python scripts/enable_scoped_executor.py`. This leaves observe mode
on and does not change policy. Never use these commands against another cluster.

From a clean committed checkout, keep all outputs outside the repository:

```sh
export AEGIS_LOCAL_EVALUATION=1
python -m evaluation.capture freeze /tmp/matched-manifest.json --corpus docs/operations --repeats 3
python -m evaluation.session /tmp/matched-manifest.json /tmp/manual-http-01 \
  --pair-id http-5xx-01 --workflow manual --operator Navin
```

Read `inputs.schedule` in the frozen manifest. Each pair contains its workflow
order. New manifests alternate manual-first and Aegis-first,15 of each across
30 pairs. This is deterministic counterbalancing, not randomization or blinding.
Do not reorder after seeing results. Existing manifests remain unchanged.

Use the explicit owned reset in the [local runbook](windows-local-trials.md#fresh-baseline-between-comparative-workflows)
before each workflow. After verifying the same baseline, run the other workflow into a
new output directory, selecting `--workflow aegis`. Repeat the frozen schedule,
not both workflows simultaneously. Save the actual reset steps and baseline
review with the session records. The controller does not erase DB history or
silently recreate a cluster. Active Aegis incident carryover blocks new Aegis
sessions; cooldown, incident history, detector history, resource use and policy
must also be inspected for pair equivalence. Matching pair IDs is insufficient.

Default session timing is180 seconds of closed-loop-load warm-up, up to120 seconds
of fault exposure plus controller/rollout time, and30 seconds after cleanup.
Sixty workflow runs therefore take several hours before resets and review, not
an hour or two. Warm-up is not proof that all detector baselines are trained.
A CI smoke uses shortened windows and is never included in the cohort.

Four request workers use identical configuration in both workflows, one request
followed by a100ms pause per worker. This is closed-loop load: actual request rate
falls when responses slow. It is not a constant offered-rate generator. Freeze
this load and the hardware for both sides. The traffic-spike fault adds the fixed
bounded eight-worker driver separately. Record actual rates, not configured ones.

## Manual versus Aegis

The manual workflow enables observe mode, blocking platform execution. A real
person uses ordinary Grafana metrics/logs and scoped kubectl in a separate
terminal, not Aegis diagnosis/Ask recommendations, to investigate and act. Type
`detected`, `action-start`, and `action-done` in the session terminal. The recorder
performs no manual remediation. Retain command history/output separately,
without credentials. Missing acknowledgements stay missing. A CI run without a
human only proves plumbing and must never be labelled a manual measurement.

Aegis requires the actual deployed Kubernetes executor and uses auto-safe mode
with the existing policy. No seeded incident, winning plan or relaxed policy is
inserted. Default rules may require approval or exclude every candidate. Report
these waits/escalations and the eligible denominator honestly. Never turn on
unsafe permissions to improve success. End-of-session safety stop selects observe,
not the old mode. The gateway supplies the authenticated actor for mode changes.

## Retained evidence and failure behavior

The session stores a hash-chained timing journal, raw domain responses, application
metrics, platform anomalies/incidents, workload/Pod/Event snapshots, source/corpus
manifest, baseline state, separate controller truth, review worksheet and a file
hash index. Keep the printed final digest separately. Integrity against a retained
anchor is not independent timestamp certification or protection against an owner
rewriting the entire log and anchor. No outcome fields are prefilled.

Samples run sequentially and have request timeouts; cadence is not exact. The
Kubernetes sampler runs separately every five seconds after each read. Read
port-forwards are restarted on connection loss; those gaps remain in the journal.
Connection errors alone do not prove an application outage or recovery. Sampling
can miss short spikes, and command application is not symptom onset.

The bounded controller still removes faults/restores state automatically. Its
first `restoration_requested` is the censoring boundary, even if the workload
looks healthy afterward. For traffic, use the earlier load completion if present.
Hook expiry, natural Kubernetes restart and fault process completion may also
restore symptoms without either workflow fixing anything. Attribute these
separately, never as a manual or Aegis action success. Review raw wall timestamps
in the controller journal, not just delayed ingestion times in the timing log.

Failures retain partial files and the comparison lock. No successful session
index is written. Interrupted runs attempt observe mode, terminate the fault
controller so its restoration runs, and close monitoring. A failed restoration
or changed workload identity requires inspection. Never delete a stale lock
without checking the real state and retaining the failed attempt. Normal
completion removes only its own comparison lock. The existing chaos lock also
prevents overlapping injection. Do not run other capture/chaos commands in
parallel with a session.

## Fixed symptom and recovery rules

Use these rules before collecting data, not thresholds chosen after outcomes.
A qualifying interval needs three consecutive valid samples unless a terminating
Kubernetes state explicitly supplies the event. Recovery needs three consecutive
valid healthy samples, no contradictory fault-specific evidence, and an actual
attributed corrective action before the earliest automatic-clear boundary.
Unobserved onset is an invalid/no-demonstrated-fault attempt, not zero latency.
A missed recovery is censored or failed, not a fabricated timeout duration.

| Fault | Independent onset evidence | Recovery and attribution checks |
|---|---|---|
| HTTP5xx | Catalog `/products`503 in three samples | Catalog200 sustained; error counter deltas cease. Hook removal/controller expiry alone earns no action credit. |
| Application-boundary latency | Catalog response elapsed time at least0.7s in three samples | Below0.7s in three samples plus baseline comparison. This is application delay, not kernel network shaping. |
| CPU saturation | Process CPU delta divided by elapsed time and actual0.2-core quota at least0.7 in four consecutive5s intervals | Same quota/identity and below0.7 for three intervals, healthy products; process counter reset is not a negative CPU recovery. Insufficient metric cadence is unknown. |
| Memory exhaustion | Increased restart count and actual `lastState.terminated.reason=OOMKilled`, exit137, compared with baseline Pod/container identity | Ready container plus sustained successful products, no continuing OOM. Natural kubelet restart is system recovery, not an Aegis/manual fix. RSS alone is not OOM proof. |
| Container crash | Increased restart count with real exit70 and termination time, same Pod UID | Ready plus successful products; distinguish kubelet restart from an attributed action. Connection loss alone is insufficient. |
| Database outage | Order `/ready` failing and Postgres replica/Pod absence independently observed | Order ready sustained and DB Pod ready. Controller scale-up does not earn workflow credit. |
| Dependency failure | Cart `/cart/evaluation-probe` failing and Redis replica/Pod absence | Cart domain success sustained with Redis ready; readiness of cart alone is insufficient. |
| Configuration error | Actual invalid catalog setting in workload template plus unavailable domain/failed container evidence | Restored valid configuration/ready Pod plus sustained products. Record template changes and command evidence. Controller restoration earns no credit. |
| Faulty deployment | Actual faulty image/revision in workload template and domain failures | Retained good image/revision restored with sustained products. Record rollback/action identity separately. A template mutation without deployment metadata is not a DI prediction result. |
| Traffic spike | Request-counter rate over5s intervals exceeds twice that session's warm-up median for three intervals, stable identity | Rate returns within twice baseline and domain/latency recovers. Bounded load ending earns no remediation credit. A spike too short or hidden by sampling is not a successful injection. |

Compute CPU and request-rate intervals from raw metric read timestamps, preserving
invalid or missing endpoints. Counter resets invalidate that interval. A CPU
series with fewer than four qualifying intervals does not pass sustained onset.
No threshold turns raw snapshots into certified ground truth automatically.

For human MTTD, use the first valid `detected` acknowledgement after independent
onset and label it acknowledgement latency. For Aegis, use the first qualifying
committed anomaly/incident record after onset, not a controller label. MTTR starts
at each workflow's own onset and ends at the start of a sustained healthy interval
only if attributable and before censoring. Record detection and recovery coverage.

Review cause ranking/citations, policy eligibility, actual execution, unsafe
closure and source identities separately. Detector confusion windows, retrieval
recall, DI pre-deploy risk/attribution and canary assessment need their own reviewed
records. This command does not manufacture those from HTTP traces. The report
must state30 pairs, one operator, small sample, non-blinding, learning/order effects,
acknowledgement timing and retained failed/unknown observations.
