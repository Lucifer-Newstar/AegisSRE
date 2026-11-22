export const dynamic = "force-dynamic";
export default function Login({ searchParams }: { searchParams: { error?: string } }) {
  return <div className="card" style={{ maxWidth: 560, margin: "80px auto" }}>
    <p className="muted">AEGISSRE / OPERATOR ACCESS</p>
    <h1>Connect to your control plane</h1>
    <p className="muted">Use your gateway operator token. It stays in an encrypted, HttpOnly session cookie for up to eight hours, never in browser storage or page data.</p>
    {searchParams.error && <p role="alert">Connection failed. Check the token and console session configuration.</p>}
    <form method="post" action="/api/session">
      <label htmlFor="token">Gateway operator token</label>
      <input id="token" name="token" type="password" required maxLength={512} autoComplete="off" />
      <button type="submit">Connect</button>
    </form>
    <p className="muted">Local demo only. A session cannot grant more access than this gateway token. Use HTTPS outside loopback or a private trusted network.</p>
  </div>;
}
