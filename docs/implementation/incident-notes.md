# Append-only operator incident context

The incident view accepts bounded operator notes through its same-origin,
CSRF-protected session. The fixed gateway route overwrites caller identity with
the authenticated principal. Blank notes and unauthorized requests are rejected.
Notes append to the audit/timeline without changing analysis, plans, approval,
execution or recovery. Corrections are additional notes, not overwritten history.

Closed-incident indexing includes the latest20 notes with actor/time under an
explicit unverified operator-context field. This context is not telemetry truth,
a command, evidence of recovery or authorization for a model to write anything.
The existing read-only tool and independent policy boundaries remain unchanged.

Native API regressions check authentication, append behavior and unchanged plan/
state. The console fixture captures the actual form pixels; the owned live-stack
gate checks the asserted gateway actor and unchanged action/state. No production
incident or user account is used for these disposable tests.
