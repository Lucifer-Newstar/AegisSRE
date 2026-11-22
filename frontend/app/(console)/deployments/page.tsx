import { loadDeployments } from "@/lib/data";

export const dynamic = "force-dynamic";

export default async function DeploymentsPage() {
  const { items: deployments, error } = await loadDeployments();
  return (
    <>
      <div className="topbar">
        <div>
          <h1 style={{ margin: 0 }}>Deployments</h1>
          <p className="muted">
            DI-1 history · live API
          </p>
        </div>
      </div>
      {error && <p role="alert">{error}</p>}
      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>Event</th>
              <th>Service</th>
              <th>Revision</th>
              <th>Status</th>
              <th>Stored</th>
            </tr>
          </thead>
          <tbody>
            {deployments.map((row) => (
              <tr key={row.eventId}>
                <td>{row.eventId}</td>
                <td>{row.service}</td>
                <td>{row.revision}</td>
                <td>
                  <span className="pill healthy">{row.status}</span>
                </td>
                <td className="muted">{row.storedAt}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
