# Actual owned-kind console capture

These six captures came from the running Next console, authenticated gateway,
PostgreSQL/Redis and actual telemetry in the disposable kind fixture.

Source head: `6dac2c36993d4698f7a21daeb28f3b93b4c47f0f`.
Run: https://github.com/Lucifer-Newstar/AegisSRE/actions/runs/45073932008/job/137366994582

Inspected all six actual screenshots. Registry health is6/6 after the exact-origin
probe fix. Out-of-scope metric panels explain scope instead of returning422;
observed charts retain short-history gaps. The service evidence table is bounded
and scrollable. Forbidden approval buttons are disabled. Runbook and postmortem
empty states are honest, not synthesized reports. Long status-pill wrapping in
the deployment table was fixed after review with nowrap; the next capture checks
that change. No C1 completion, evaluation timing or model inference is implied.
