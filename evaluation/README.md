# Held-out reporting contract

Run `python -m evaluation.report input.json result.json` to validate independently
collected records and write an immutable JSON report. This reporter does not
inject faults, invent a manual comparator, certify references/digests or create
research results. No measured dataset is included yet. Unit inputs are authored
schema tests only and are not evaluated observations.

The input schema is defined by `Dataset` and `Run` in `report.py`. It requires
independent truth and observation references, frozen manifest/corpus/environment
SHA256 identifiers, workflow/pair IDs and an attributed manual observer. Paired
runs must agree on those identities. Dates must carry offsets; observations
outside the declared interval are rejected. Ten completed runs per fault and
workflow are counted separately from project quality thresholds.

The report preserves attempted, timeout, failed and censored counts. Missing
MTTD/MTTR and sample standard deviation with fewer than two observations are
null, never zero. Means/std use observed intervals, so read coverage alongside
them. Unsafe closure counts, RCA/verification coverage and eligible/executed
opportunity denominators remain visible. Paired differences use each run's own
onset, not cross-run wall-clock subtraction. No statistical significance or
project acceptance is claimed by an adequate repetition count.

Still required: frozen manifests/corpus and reviewed truth, automatic collection
of independent observations, at least ten runs per fault/workflow, a genuine
human manual baseline, detector confusion-matrix windows, retrieval/DI metrics,
reviewed model answers and committed measured results. Do not fill those gaps
with synthetic events or assumed human delays.

## Detector, retrieval and deployment-quality metrics

`python -m evaluation.quality input.json output.json` checks reviewed independent
window/retrieval/deployment observations and computes detector confusion matrix,
precision/recall/F1, observed latency, recall@5, pre-deploy risk recall, rollout
flag timing, revision attribution and eligible rollback recovery. Unknown scores
remain in the faulty-deployment denominator. Empty cohorts are null. Duplicate
IDs, overlapping detector windows, post-deploy predictions and duplicate retrieved
IDs are rejected. Thresholds are fixed, not selected for a passing result.

This is reporting infrastructure only. No measured dataset is supplied. The
manifest/corpus digests and review/source references are declarations, not
independently certified by the reporter. Human truth review, a frozen held-out
corpus, repeated faults and genuine manual response observations remain needed.

## Frozen raw capture, not a benchmark result

On a clean committed checkout, first freeze the exact source revision, Kubernetes
manifest files and the selected reviewed corpus. Keep output outside the checkout:

```sh
python -m evaluation.capture freeze /tmp/aegis-manifest.json --corpus docs/operations
python -m evaluation.capture trial /tmp/aegis-manifest.json /tmp/aegis-trial-01 \
  --fault http-5xx --seconds 30 --repeat 1
```

The second command requires the current run's newly owned disposable kind fixture
from `scripts/ci/kind_platform_gate.py`. It refuses other clusters. It performs
one bounded Aegis trial only, never a hosted matrix. The frozen manifest enumerates
100 paired experiment IDs, ten repetitions for each of ten faults, but neither
command automatically launches that schedule or generates human observations.
The example operations directory is a corpus input, not a claim that it is a
reviewed held-out evaluation corpus.

Capture verifies source cleanliness, revision and actual file hashes before each
trial. A fresh exclusive output directory stores the manifest, observed workload/
Pod specifications, independent request status/latency, raw application metrics,
and platform incident snapshots. The separate chaos control journal records
injection/restoration operations. No fault label is sent to the platform. Reads
are fixed localhost fixture endpoints, bounded, without redirects or proxies.
Capture includes ten seconds before injection and thirty seconds after the
runner returns; the collector samples sequentially with a two-second pause, so
request/timeout duration can lengthen the cadence. Sample timestamps are not
certified symptom-onset or detection timestamps. A restarted Pod can invalidate
a port-forward; connection errors are retained, not called an outage or recovery.

The index hashes all successful capture files and is explicitly
`captured_not_reviewed`. Incomplete runs leave their partial files without a
success index. No report-schema dataset, claimed MTTD/MTTR, manual baseline,
causal diagnosis, safety verdict, or acceptance result is manufactured. Control
restoration after the bounded fault must not be credited to Aegis remediation.
Review independently observed symptom onset, first qualifying detection, actual
recovery, action attribution and any censored/failed intervals before creating
`report.py` inputs. A human must actually perform and record manual trials;
matching `pair_id` strings alone do not prove identical environments.

Dependency trials observe the actual affected boundary: database outage reads order
readiness and its platform records; Redis dependency outage reads a cart-domain
endpoint and its platform records. Other faults observe catalog products. Each
sample also retains the affected service's committed anomaly events and raw
metrics. Empty results and connection errors remain explicit. Successful snapshot
capture alone never certifies that an injection produced its intended symptom.

## Approved final small-sample comparison (November23)

The owner approved a smaller genuine comparison rather than inventing100 manual
runs: target30 manual trials with Navin and one friend, paired with30 Aegis trials,
three repetitions of each of the ten faults. Friend identity and actual trial
observations remain to be supplied. Run locally and small, never a hosted matrix.
No trial is performed merely by selecting this profile.

Freeze that explicit design with `--repeats 3`. In the reviewed `report.py` input,
set `comparison_profile` to `approved_small_3_per_fault`. The report records
`small_sample: true` and requires three completed runs per fault/workflow plus
pairing. The unchanged default profile still requires ten. Small-sample completion
does not satisfy the original ten-per-fault design, establish significance, or
waive detection, correctness and safety reporting. Failed/censored attempts remain
visible. The owner did not authorize fake observations or a paid runner.

Model inference and deeper training/registry/drift work are unbuilt roadmap ideas,
not final-release requirements. Existing evidence-only answers, statistical/IF
detection, retrieval and planned deployment-risk/canary scoring remain the actual
final scope. No model downloads/calls will be made for this release.
