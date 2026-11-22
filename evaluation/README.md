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
