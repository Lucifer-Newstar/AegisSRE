# Detector sample evidence

Ingest commits a detector anomaly-sample marker in the same transaction as its
metric and incident update. A scoped authenticated API returns markers for the
requested aggregate service/environment/metric in the latest5000 metric source
events within24h. Truncation is explicit. Legacy events are not re-detected using
a future baseline. Missing markers are not evidence of no anomaly.

Charts draw red lines at producer sample timestamps with evidence IDs and scores.
These markers are separate from incident-context shading and from independently
measured fault intervals. Recovery duration and onset are not guessed from them.
The API uses one bounded batch lookup rather than one database query per sample.
