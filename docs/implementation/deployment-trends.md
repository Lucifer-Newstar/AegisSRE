# Deployment cohorts and reviews

The authenticated trends API returns 30 UTC start-day cohorts using scoped SQL
counts. CFR is unknown for empty, unknown-outcome, or unidentified cohorts.
The chart breaks across gaps, and daily counts/coverage remain inspectable.
These are current observations grouped by start day, not historical snapshots:
late evidence can change previous cohorts. No causal accuracy is claimed.

Each window links to a scoped deployment review with source/observation IDs,
frozen risk, observed outcome, recorded incident actions, and a closed-incident
postmortem link only when available. A deployment review is not passed off as
an AI-authored causal report. Absent actions/recovery stay absent.

Unit tests cover UTC boundaries, future rows, empty cohorts, missing outcomes,
and service/environment isolation. The live runtime gate checks actual gateway,
metadata, persistent SQL, and restart wiring with explicit synthetic inputs.
The checked-in screenshot is a visual fixture, not live fault proof.
