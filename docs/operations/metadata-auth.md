# Metadata service authentication

Registry and deployment data can steer incident investigation. Both services now
require internal bearer credentials before business routes or request bodies are
processed. There is no production default key. This boundary does not enable a
remediation executor or change an autonomy policy.

## Credentials and routes

Set distinct, nonempty values through your local untracked environment or secret
manager:

| Process | Variable | Access |
|---|---|---|
| Registry and deployments | `AEGIS_METADATA_API_TOKEN` | Operator reads and writes. |
| Registry and deployments | `AEGIS_METADATA_READ_TOKEN` | GET/HEAD only, including readiness. |
| Gateway | `AEGIS_GATEWAY_METADATA_TOKEN` | Internal operator credential, never the caller's key. |
| Reliability collector/indexer | `AEGIS_METADATA_TOKEN` | Internal read-only credential. |

Compose maps the two metadata values to the right consumers. The user-facing
`AEGIS_API_TOKEN` remains separate. Do not put any service key in browser code,
`NEXT_PUBLIC_*` values, screenshots, a tracked file, or a chat. Restart the
relevant processes after rotating credentials; hot key rotation is not provided.

Only `GET /health` and `GET /metrics` are public. The root, readiness, catalogue,
deployment history, schema and docs routes require a valid service key. A valid
read-only key cannot POST, PUT, PATCH or DELETE. Duplicate/malformed authorization
headers fail closed. WebSocket access is refused. Configured keys still apply in
dev mode. Unauthenticated native development requires explicitly setting
`AEGIS_METADATA_DEV_MODE=true` and leaving both keys unset. Compose forces this
mode off.

Authenticated POST/PUT/PATCH bodies are bounded to 64KB, including chunked bodies.
Authentication precedes body collection. The gateway replaces caller credentials
with the configured internal key and does not forward cookies. The collector and
indexer attach their read key only to their configured metadata calls, not
Prometheus, Loki or Tempo. Owned HTTP clients ignore ambient proxy variables and
reject redirects. Origins still belong to trusted operator configuration.

This is a shared service credential boundary, not per-user roles or multi-tenant
isolation. A deployment's `triggered_by` is a producer-supplied label, not proof
of a human's identity. Gateway incident decisions separately bind the audit actor
to its configured operator principal. Full network isolation and integrated kind
bootstrap remain acceptance work. The local demo uses HTTP inside its private
container network; this is not production transport/security approval.

## Running and checking

For Compose, fill the three distinct blank API/token settings in `.env.example`
after copying it to an untracked `.env`: the user API token and two metadata
keys. Compose reads that file, but Python smoke helpers do not. Export the two
metadata variables into the helper's shell using your secret workflow before
running the isolated-stack checks in [local setup](../development/local-setup.md).
Do not run fixture seed/delete checks on a real catalogue.

The metadata smoke job verifies unauthenticated denial, read-only access,
read-only write denial, actual operator writes, PostgreSQL persistence and
application restart. The full runtime job separately proves authenticated
collector/indexer/gateway integration. Unit tests use explicit local dev mode or
disposable test keys, not real credentials. Hosted results must pass before merge.

Metadata images run as UID/GID 10001. Their default standalone SQLite location is
`/data/aegis-metadata.db`; mount persistent storage there if using that mode.
Compose uses PostgreSQL instead. Kubernetes bases reference the
`aegissre-metadata` Secret's `api-token` and `read-token` keys. Readiness uses a
local exec probe that reads the environment key without putting it in the Pod
manifest or probe arguments. Liveness and metrics need no key. The bases also
use a non-root, read-only root filesystem, no ambient service-account token, and
a bounded writable `/tmp`. These manifests still need full-stack kind acceptance.

The current console remains an explicitly labelled scaffold. It is not given a
metadata key to bypass its missing login/session boundary. Direct server reads
can therefore fall back to its existing mock state. The live console milestone
must replace that path with authenticated gateway access and remove mock fallback.
