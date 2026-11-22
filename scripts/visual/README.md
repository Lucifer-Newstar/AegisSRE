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
