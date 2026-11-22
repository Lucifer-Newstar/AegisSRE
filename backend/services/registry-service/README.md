# Registry service

Port 8101. [Contract](../../../docs/contracts/registry-service.yaml).

The catalogue is durable: PostgreSQL in Compose, an ignored local SQLite file
for native development, and isolated memory stores for tests. `DATABASE_URL`
selects the backend. Readiness checks the actual configured store and returns
503 on failure. It does not pretend to have checked Redis.

The API supports create/read/update/delete plus heartbeat. Records include an
owner, availability SLO and latency SLO. Seed services start with unknown health;
registration is not evidence that a workload is running. With
`REGISTRY_PROBE=true`, bounded `/ready` probes refresh on a 15-second cadence.

Probe hosts must appear in `REGISTRY_ALLOWED_HOSTS`, a JSON array of service DNS
names. The default is the project's service names. Probe URL credentials and
redirects are rejected to avoid a probe becoming a general network fetcher.

Deletion uses a persisted tombstone so a deleted default service does not return
on restart. A later registration can explicitly recreate it. In-flight probe
results cannot resurrect deleted records or overwrite changed metadata.

The service is currently an internal/local API. Compose binds its host port to
127.0.0.1. The authenticated gateway and complete cluster network isolation are
separate runtime-integration work, not a claim of production readiness.

For a manual container build, use the repository root as build context:

```bash
docker build -f backend/services/registry-service/Dockerfile .
```
