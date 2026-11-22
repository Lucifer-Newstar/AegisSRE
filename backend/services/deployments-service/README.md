# Deployment history service

Port 8701. [Contract](../../../docs/contracts/deployments-service.yaml).

Deployment envelopes persist to PostgreSQL in Compose or an ignored local SQLite
file during native development. `DATABASE_URL` selects the backend. Readiness
checks that actual database and returns 503 on failure.

An identical event id/content is idempotent. Reusing an id with different content
returns 409 and preserves the original event. Latest/history order uses producer
time, then receive time to break ties. An old event arriving late does not become
the latest deployment. Producer timestamps must include a timezone.

History starts empty. Startup does not invent a v0.1.0 deployment for every
service. If `DEPLOYMENT_REVISION` is explicitly supplied, this service records
its own first-seen running revision only. Deployment hooks or API clients must
supply real workload deployment events. The intelligence/rollout tier builds on
this history in a later milestone.

The service is currently an internal/local API. Compose binds its host port to
127.0.0.1. The authenticated gateway and complete cluster network isolation are
separate runtime-integration work.

For a manual container build, use the repository root as build context:

```bash
docker build -f backend/services/deployments-service/Dockerfile .
```
