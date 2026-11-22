import Link from "next/link";
import { loadServices } from "@/lib/data";

export const dynamic = "force-dynamic";

export default async function ServicesPage() {
  const { items: services, error } = await loadServices();
  return (
    <>
      <div className="topbar">
        <div>
          <h1 style={{ margin: 0 }}>Services</h1>
          <p className="muted">
            Registry A2 · live API
          </p>
        </div>
      </div>
      {error && <p role="alert">{error}</p>}
      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>Id</th>
              <th>Name</th>
              <th>URL</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {services.map((svc) => (
              <tr key={svc.id}>
                <td><Link href={`/services/${encodeURIComponent(svc.id)}`}>{svc.id}</Link></td>
                <td>{svc.name}</td>
                <td className="muted">{svc.url}</td>
                <td>
                  <span className={`pill ${svc.status}`}>{svc.status}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
