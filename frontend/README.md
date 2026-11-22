# AegisSRE console foundation

Next.js control-plane UI, port 3030. The console uses the fixed authenticated API
gateway, never unauthenticated metadata reads or mock fallback. API failures are
visible; missing timings are not zero and unknown service health is not healthy.

Configuration:

- `AEGIS_CONSOLE_GATEWAY_URL`: server-only gateway origin, default loopback8080.
- `AEGIS_CONSOLE_ORIGIN`: exact browser origin, default `http://localhost:3030`.
- `AEGIS_CONSOLE_SESSION_SECRET`: independent encryption secret of at least32
  bytes. Login fails closed without it. Kubernetes reads `session-secret` from
  the externally created `aegissre-console` Secret.

Enter an existing gateway operator token in the local login page. The server
validates it through the gateway, then stores it only inside an AES-256-GCM
HttpOnly/SameSiteStrict cookie with an eight-hour lifetime. No localStorage,
embedded token, auto-login environment token or public proxy exists. HTTPS uses
Secure cookies. Plain HTTP is local-demo convenience, not safe internet hosting.
All decision/Ask/logout POSTs require the exact Origin and per-session CSRF value.
Only fixed server-selected endpoints are reachable; redirects are rejected,
request/response reads are bounded and API actor identity remains gateway-owned.
Logout deletes this browser cookie, it does not revoke the underlying gateway
token. There is no central session revocation until token/key rotation.

Pages now read real API contracts for overview, services/details, incidents/
details, approvals, postmortems, runbooks, Ask, deployments and audit. Approval
records a decision, it does not silently execute remediation. Ask exposes only
read tools and displays inference status, tool calls and citations. Raw structured
report/evidence views are an interim presentation, not finished product UX.

Remaining C1/product work includes metric charts and anomaly shading,24h
sparklines, SLO budget/burn panels, structured postmortem export, deployment
risk/canary views and full interaction acceptance. Do not call this the complete
eight-page acceptance simply because routes exist.

`npm test` checks session encryption/tamper/expiry/CSRF and origin configuration;
`npm run build` checks actual Next/TypeScript compilation. The hosted owned-kind
proof must additionally log in against the real gateway and read all routes,
reject a cross-origin decision and confirm tokens never appear in page bodies.
Local screenshot checks used an explicitly synthetic HTTP fixture, not real
telemetry or measured project results. No user token was used in those images.
