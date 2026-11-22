# Read-only intelligence and Ask Aegis

Ask uses a fixed read-only tool set: persisted metrics, logs, traces, health,
deployment history, Kubernetes events, and scoped knowledge retrieval. The tools
accept an allowed service, not arbitrary URLs, SQL, shell commands or action
names. They cannot approve or execute remediation. Kubernetes evidence remains
missing until a real Kubernetes collector is configured and implemented.

## HTTP surface

All routes below require the reliability bearer token. The gateway exposes the
same routes under `/api/v1`, using its separate operator token.

| Method | Route | Purpose |
|---|---|---|
| POST | `/ask` | Body: `service`, `question`. Return answer, engine, inference status, citations and tool snapshot. |
| GET | `/intelligence/tools?service=catalog-service` | Inspect the fixed tools and persisted evidence without inference. Optional `question` steers knowledge retrieval. |
| GET | `/intelligence/status` | Provider/model, configured request limits, dated reservations, zero retries and empty write-tool list. No API key is returned. |
| POST | `/incidents/{id}/investigate` | Gather a current scoped service snapshot, optionally infer, and save a read-only sidecar if the incident revision still matches. |
| GET | `/incidents/{id}/investigation` | Read the saved snapshot and whether its incident revision still matches. |

A snapshot returns the exact source event reference or knowledge document ID,
opaque event citation IDs, versioned knowledge chunk IDs, selected content,
observed/index times, tool check times and missing/stale/unavailable status.
Event freshness is bounded per tool. A fresh event does not prove the collector
is healthy. No events, zero traffic, stale events or a missing source must not be
translated into an overall healthy service. Reference documents are not current
observations, and index time is not source observation time.

Tools return at most two persisted events per source type and three knowledge
chunks. This is a bounded investigation readout, not an exhaustive log query.
Inspect `/knowledge/status` and `/runtime` separately for index and collector
failures. Investigations currently use current service evidence, not an arbitrary
historical incident window. Their capture time and per-source freshness remain
part of the result, including when investigating an old incident.

## Disabled mode and failures

`AEGIS_LLM_PROVIDER=disabled` is the default. It constructs no inference client
and returns `engine=evidence-only-v1`, `inference_status=disabled`. The summary
is a count/readout of actual persisted observations, not a generated diagnosis.
It does not pretend a model ran.

A configured provider failure returns `inference_status=failed`, a diagnostic
code and an explicitly labelled evidence-only fallback. It does not silently
substitute a model answer. Successful inference returns
`engine=structured-llm-v1`, the selected model and `inference_status=complete`.
This is an unverified interpretation, not proof of cause or health.

## Optional inference configuration

Set these only after choosing the model, endpoint, evidence disclosure and cost
policy. Enabling an external endpoint sends selected telemetry and question text
to that endpoint. Best-effort redaction is not a guarantee that every secret or
piece of personal data has been removed.

| Setting | Default | Meaning |
|---|---|---|
| `AEGIS_LLM_PROVIDER` | `disabled` | `disabled`, `ollama`, or OpenAI-compatible `openai`. |
| `AEGIS_LLM_URL` | `http://localhost:11434` | Fixed base origin/path. Ollama appends `/api/chat`; OpenAI-compatible appends `/chat/completions`, so its base normally includes the API version path. |
| `AEGIS_LLM_MODEL` | empty | An explicit model supporting the selected structured-output protocol. No automatic model download. |
| `AEGIS_LLM_API_KEY` | empty | Optional bearer credential, supplied through the deployment's secret mechanism, never committed. |
| `AEGIS_LLM_ALLOW_REMOTE` | `false` | Explicit selected-evidence egress opt-in. Outside loopback and the documented local container names, HTTPS and this flag are required. Private IP addresses do not imply permission. |
| `AEGIS_LLM_TIMEOUT_SECONDS` | `30` | Hard inference timeout, 5 to 120 seconds. |
| `AEGIS_LLM_MAX_OUTPUT_TOKENS` | `1024` | Provider output cap, 128 to 4096 tokens. Not a total input/output currency budget. |
| `AEGIS_LLM_REQUESTS_PER_HOUR` | `10` | Durable shared hourly reservation cap, UTC buckets. |
| `AEGIS_LLM_REQUESTS_PER_DAY` | `50` | Durable shared daily reservation cap, UTC buckets. |

The local container names are `ollama` and `host.docker.internal`; the latter
must actually resolve in the deployment. Compose does not bundle a model server.
`localhost` inside a container is that container, not the host. Set a reachable
approved endpoint rather than assuming a host model can be reached there.

Request reservations commit before network inference and survive restart.
Concurrent processes sharing the database cannot each spend the same slot.
Failed calls consume a slot and there are no automatic retries. The caps are
request limits, not a financial spending limit. Account-level provider budgets
and explicit cost approval are still needed. Ask and incident investigation use
the same ledger. No question or provider response is written to the quota audit.

## Boundaries and validation

- Evidence collection finishes its SQL transaction before retrieval/inference.
  Model latency does not hold an incident lock or block the telemetry worker.
- The transport has a 24KB input bound, 64KB response bound, fixed endpoint,
  redirect refusal, compression refusal and hard timeout. It sends no model tool
  definitions. Refusals, truncation and unexpected tool calls are rejected.
- Only selected bounded fields enter context. Sensitive keys, common inline
  secrets, bearer/JWT text and common connection URLs are redacted. Do not treat
  this heuristic as a complete data-loss-prevention system.
- Local strict schema validation rejects extra fields and unknown cause names.
  Every citation must resolve to a supplied snapshot ID. Each hypothesis must
  cite a non-stale observation, not only a reference document. This validates
  citation identity and freshness, not whether prose logically proves a cause.
- Model output never modifies the executable plan, approval, incident state or
  autonomy policy. Investigation writes only its sidecar. A changed incident or
  snapshot older than 120 seconds rejects the write with HTTP 409. A later read
  reports whether the saved incident revision still matches.
- Prompt-like instructions in logs, traces and documents are untrusted data.
  No write tool is exposed even if a model asks for one.

## What the checks prove

Native tests exercise the two wire protocols with explicit mock transports,
citation rejection, scope, secret redaction, failure visibility, detached SQL,
request caps/restart and incident-revision races. They are not live model tests.
Hosted storage CI additionally checks actual PostgreSQL concurrent reservations.
Hosted Compose CI asks through the real gateway and resolves returned metric
citations back to actual collected persisted events. That gate deliberately runs
with inference disabled and does not claim model quality.

Live model acceptance, ranked accuracy on the real ten-fault evaluation, complete
Kubernetes evidence and the Ask console view remain separate acceptance work.

Protocol references checked for this implementation:

- [Ollama chat](https://docs.ollama.com/api/chat)
- [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs)
- [OpenAI-compatible chat contract](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
