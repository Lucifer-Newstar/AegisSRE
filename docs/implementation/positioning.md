# Project positioning

AegisSRE is an SRE + DevSecOps project with a small planned MLOps layer.
The [acceptance ledger](status.md) is the source for what is implemented and
measured. Do not turn planned features or synthetic tests into resume results.

## Resume wording supported by implemented code

**AegisSRE | SRE, DevSecOps, Python, FastAPI, PostgreSQL, Redis, Kubernetes**

- Built a telemetry-driven reliability runtime with durable event processing,
  anomaly detection, evidence-linked incidents, approval and recovery checks.
- Added DevSecOps controls: separate read/write service credentials, bounded
  authenticated APIs, hardened non-root containers, audit, and disposable CI
  checks for persistence, transport and Kubernetes read permissions.
- Added identified deployment observation windows and change-failure analytics
  that keep missing evidence unknown rather than calling it healthy.

Do not add model accuracy, detection latency, MTTR or real-cluster recovery
numbers until the evaluation harness has measured them. The executor defaults
to simulation. The existing Isolation Forest anomaly detector is not proof of
implemented predictive deployment risk or canary scoring.

## Portfolio introduction

AegisSRE explores evidence-backed SRE with visible DevSecOps boundaries. It
collects telemetry, persists incident decisions and keeps remediation behind
policy, approval and recovery checks. Its small MLOps scope is the planned
risk/canary scoring, not a general-purpose model platform. Implementation and
measured acceptance are tracked separately.

## V2 boundary

Full training pipelines, a model registry and model drift pipelines are v2
roadmap ideas, not current deliverables. Finish and evaluate the planned risk
and canary scoring before widening that scope. Live model choice remains an
operator decision; this document authorizes no model download, remote inference
or spending.
