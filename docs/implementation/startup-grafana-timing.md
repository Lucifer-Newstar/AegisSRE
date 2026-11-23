# Application-start telemetry timing

`scripts/check_startup_grafana.py` measures the A1 application-start boundary in
the owned disposable cluster. After the existing stack is ready, it restarts
catalog, identifies a new Pod UID and its actual container `startedAt`, and polls
the authenticated Grafana provisioned Prometheus datasource. The observed
`process_start_time_seconds` must belong to the newly started process, not a
stale series from the old Pod. Observation must be less than sixty seconds after
container start, or the gate fails. A JSON proof retains times, identity, query,
result and elapsed seconds. No result is supplied by the script itself.

This is a backend telemetry-availability timing check through Grafana, not pixel
proof or a cold full-stack bootstrap result. Images, cluster, database, collectors
and Grafana are already running. Full-stack cold startup remains a separate
measurement. Existing Grafana screenshot and SLO tests cover rendering and
provisioned panels separately.
