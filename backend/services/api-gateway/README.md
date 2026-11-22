# API gateway

A thin authenticated entrypoint for the existing registry, deployment and
reliability APIs. Routes are compiled in `api_gateway/routes.py`; callers cannot
supply an upstream origin or arbitrary path. The browser console is not yet
switched to this entrypoint. Its session/login and live-page work remains open.

## Run

Python 3.12+, Redis 7+ and the three backend APIs are required. Install this
package and its dependencies or run `docker compose up --build api-gateway`.
Compose reads `AEGIS_API_TOKEN` from the untracked local environment and binds the
gateway to `127.0.0.1:8080`. The default does not supply a token. Native settings
use the `AEGIS_GATEWAY_` prefix:

- `API_TOKEN`: the gateway operator credential, required.
- `INCIDENTS_TOKEN`: the backend integration credential, required.
- `REGISTRY_URL`, `DEPLOYMENTS_URL`, `INCIDENTS_URL`: fixed HTTP(S) origins.
- `REDIS_URL`: shared distributed rate-limit state.
- `REQUESTS_PER_MINUTE`: authenticated principal limit, default 120.
- `FAILED_AUTH_PER_MINUTE`: failed-auth source limit, default 30.
- `OPERATOR`: authenticated audit label, default `token:operator`.

All `/api/v1/*` routes require `Authorization: Bearer <gateway-token>`. Only
`/health` is public. `/api/v1/ready` checks Redis and bounded readiness responses
from each configured backend. Interactive docs are not served by the gateway;
its generated contract is in `docs/contracts/api-gateway.yaml`.

## Boundaries

- Redis-backed atomic fixed windows do not extend with each request. Redis failure
  closes access with 503. Limits are shared across gateway processes. Failed
  auth is keyed by the actual connection source, not a spoofed forwarded header.
- Route/path/query allowlists, 64KB bodies, bounded responses and timeouts apply.
  Redirects are rejected. GET bodies are rejected. No generic URL proxy exists.
- Incoming cookies and authorization are not forwarded. Backend credentials come
  only from server configuration. Upstream cookies are not retained or returned.
- Approval, execution and autonomy writes use the configured token principal as
  actor, not an arbitrary name supplied in the request body.
- Request IDs are bounded and propagated. Data responses are not cacheable.
- No write is retried automatically. If a write times out, read its business state
  before deciding whether another attempt is safe. Execution may still be running.

The current credential identifies one operator, not a multi-user role system.
Metadata backend APIs remain available on host loopback for local diagnostics;
full production network policy/internal authentication is still part of cluster
hardening. The existing console is still a scaffold, not a finished authenticated
UI. No real infrastructure action is part of gateway testing.

## Checks

`tests/test_gateway_boundary.py` covers auth-before-body, fixed routing,
credentials/cookie separation, principal-bound actor labels, bounded responses,
readiness, Redis failure and shared rate-window behavior. Hosted Compose adds
`scripts/check_gateway_stack.py`: actual auth/routing/correlation and approval of
a controlled CI incident, with no execution requested. These checks are not a
real-cluster or anomaly/RCA acceptance benchmark.
