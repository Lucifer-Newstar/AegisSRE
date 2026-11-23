# Scoped product acceptance proofs

These are actual integration observations, not held-out benchmark results.

| Proof | Exact checked head | Source run | Result and limits |
|---|---|---|---|
| Operator note and scope display | `776f5595d2233906ccd0cdbf3445b53421747b7a` | [CI job](https://github.com/Lucifer-Newstar/AegisSRE/actions/runs/45101877929/job/137454492072) | Actual HTML form wrote one gateway-attributed note. Cross-origin403 and bad-CSRF422. Plan, action state and approval unchanged. The seeded incident is outside related-runbook scope, now shown explicitly without cross-scope retrieval. |
| Approval interaction | `c2f4b433ed4f2c1b7db1561e12f6f3e10ad77c80` | [CI job](https://github.com/Lucifer-Newstar/AegisSRE/actions/runs/45101879809/job/137454498494) | Two clicks from authenticated command center, login excluded. Reason/impact present, decision audit incremented and gateway principal recorded. No action execution. Seeded fixture, not fault response. |
| Application-start telemetry | `7a0d9da3e809243e621aa2e07d41d9605a90caa0` | [CI job](https://github.com/Lucifer-Newstar/AegisSRE/actions/runs/45101881504/job/137454455318) | New application process metric observed through authenticated Grafana datasource in22.55s after container start. Collectors already running. Not cold full-stack timing or pixel proof. |
| Frozen raw capture | `dcb891a31f64c4cccfb634ae83248cb2653da238` | [CI job](https://github.com/Lucifer-Newstar/AegisSRE/actions/runs/45099486927/job/137446778408) | One five-second HTTP fault with raw200/503/200 observations and separate control truth; manifest, environment, observation and control hashes verified. Not a reviewed outcome dataset or manual comparison. |

All eleven checks passed on each listed head before its ordinary merge.
The JSON files in [evidence](evidence/approval.json) retain the original scoped
proof fields, without adding unmeasured outcomes:
[operator note](evidence/operator-note.json), [approval](evidence/approval.json),
[startup Grafana](evidence/startup-grafana.json).

Actual final images were inspected for readable layout, visible success/audit
and honest missing-data or scope text:
[operator form](../screenshots/operator-form/owned-kind.png),
[approval confirmation](../screenshots/approval-form/owned-kind.png).
The approval screenshot shows remaining unrelated pending incidents after the
seeded incident's successful approval. It does not imply those were approved.

Still open: repeated fault cohort, independently reviewed detection/recovery and
RCA truth, a genuine human comparator, retrieval/DI
thresholds and full product acceptance. The scoped observations above do not
satisfy those distinct gates.

## Matched-session proof, not a measured comparison

[The controller CI job](https://github.com/Lucifer-Newstar/AegisSRE/actions/runs/45119252520/job/137509139711)
retained73 hash-verified timing records,14 actual503 probes and37 healthy probes.
The first restoration boundary and observe safety stop were recorded. The
operator was explicitly `ci-smoke-not-human`, there were no human acknowledgements,
and all reviewed outcome timestamps remained null. This is plumbing proof only.

The integrated workflow, reviewed report path and local reset are documented in
[matched trials](../development/matched-trials.md),
[reporting](../../evaluation/README.md) and
[Windows local trials](../development/windows-local-trials.md). The local reset
has unit safety checks; its actual target-laptop validation remains open.
