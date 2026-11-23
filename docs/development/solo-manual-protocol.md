# Solo manual comparison protocol

One human can perform the manual workflow. A friend is optional, not a gate.
The recorder supplies probe/monotonic timing; it does not diagnose or fix faults.
This is still a single-operator small-sample study, not a blinded independent trial.

## Before the first pair

- Verify the local-owned Windows/WSL2 smoke and resources first. Never use another
  cluster. Freeze source, service manifests, corpus and the approved3-per-fault
  design. Use30 paired experiments, ten faults with three repetitions each.
- Fix the probe boundary and fault-specific symptom/recovery criteria before
  collecting results. HTTP status alone cannot establish CPU saturation, memory
  exhaustion, traffic spike or correct recovery. Preserve the corresponding raw
  metrics/Kubernetes events and qualifying detector records too.
- Generate and retain the experiment order before running it. Balance manual-first
  and Aegis-first pairs. State that a solo operator can still learn from prior
  runs and may know the fault schedule. Randomization does not remove that bias.
- Hold configuration, offered load and initial state constant within each pair.
  Restore baseline and allow normal detector warm-up before each workflow. Record
  resource contention and any prior-incident/cooldown carryover, do not hide it.

## Human session recorder

In the local-owned WSL shell:

```sh
export AEGIS_LOCAL_EVALUATION=1
python -m evaluation.manual /tmp/manual-http-01 --operator Navin --pair-id http-5xx-01
```

Use `--boundary cart` for Redis dependency trials and `--boundary order` for
Postgres outage readiness; otherwise the catalog boundary is the starting probe.
These are fixed endpoints. The recorder owns the port-forward, samples actual
responses and writes a flushed hash-chained journal with wall/monotonic times.
It does not inject a fault, reveal a fault label, execute commands, call a model
or simulate a person. In a separate terminal, Navin actually uses conventional
monitoring/logs/kubectl to investigate and perform an allowed manual action.

Type `detected` when acknowledging the observed problem, `action-start` before the
manual action, and `action-done` afterward. These are timestamped acknowledgements,
not automatic claims of first awareness, successful commands or recovery. Type
`stop` to finish. The maximum session is600s by default; expiry records its own
monotonic timestamp and stops probes even if the prompt still awaits a key.

Preserve the final digest separately with the frozen report record before editing
any worksheet. `evaluation.timing.verify` checks sequence, hash links, monotonic
ordering and the retained final digest. This detects changes against that anchor;
it is not tamper-proof against a machine owner rewriting the entire log and
anchor. An external reviewer or separately stored digest strengthens provenance.
Do not claim independent timestamp certification.

## Outcome review and fair attribution

- Independent onset is the first predefined qualifying symptom interval, not the
  injection command time. MTTD on the human side uses the recorded acknowledgement
  and must be labelled acknowledgement latency. Review missing/late acknowledgements.
- Recovery is the first predefined sustained healthy interval after an actual
  corrective action, with health/error/latency/SLO and fault-specific evidence.
  `action-done` is not recovery. Retain censored/failed/unknown results.
- Mark every safety/controller cleanup separately. The existing timed chaos smoke
  restores state automatically; recovery caused by that timer is not credited to
  manual response or Aegis. A timeout followed by cleanup remains a timeout.
- The Aegis workflow must use its actual deployed scoped executor and policy.
  Record approval waits separately. A forbidden/unsupported action escalates;
  do not waive policy or seed a winning plan to manufacture eligible success.
- No one types synthetic manual delays or copies Aegis detection timestamps into
  the manual record. A solo human really performs each manual trial.

Use the [matched-session controller and fixed review criteria](matched-trials.md)
for integrated bounded fault sessions. The standalone recorder remains useful
for separate observation. Actual laptop sessions and reviewed outcomes are still
required before results count.
The report must disclose30 pairs, one operator, small sample, non-blinding,
learning/order effects, timing-acknowledgement semantics and any external review.
Automatic probes remove stopwatch arithmetic, not these limitations.
