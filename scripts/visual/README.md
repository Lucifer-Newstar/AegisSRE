# Local console fixture check

Prerequisite: Node 22, the frontend dependencies, and a successful
`npm --prefix frontend run build`. Then:

```sh
npm --prefix scripts/visual install
cd scripts/visual
npx playwright install chromium
npm run check
```

Requires local ports 3030 and 18880 free. Output defaults to
`/tmp/aegis-console-visual`; set `AEGIS_VISUAL_OUTPUT` to choose another folder.
Both HTTP servers and the browser are closed on exit. The API is an explicitly
synthetic localhost fixture. It does not connect to the user's platform, call a
model or take an action. Its disposable token is not a real credential.

Checks actual Next login, protected pages/cookie, no fixture token in HTML,
cross-origin mutation denial, report export, literal runbook HTML, navigation
and chart rendering. Inspect the saved pixels separately before accepting a
visual result. This is not the real gateway/kind proof or fault acceptance.

`operator-note.mjs` runs only inside the existing owned cluster gate. It logs in
through the real console, submits the operator-note HTML form, verifies one durable
note with the gateway-bound principal, and asserts status/approval/plan/undo did
not change. Cross-origin and invalid-CSRF posts must be rejected first. It stores
a JSON proof and final screenshot for separate pixel inspection. The integration
incident is seeded test evidence, not a naturally detected fault. This test does
not approve a plan, invoke an action or call a model.

`approval.mjs` verifies the A7 click bound through the live console against the
unique seeded `ci-runtime` incident. From the authenticated command center,
it clicks Approvals and approve, after checking that reason/impact are present.
Login is excluded and recorded separately. It confirms the gateway actor,
audit increment and unchanged action state, and does not invoke execution. It
first defers only that existing seeded fixture so the approval is pending again.
A JSON proof and screenshot are retained; this is interaction evidence, not
fault-detection, inferred RCA or autonomous remediation acceptance.
