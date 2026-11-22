import Link from "next/link";
import { Incident, load } from "@/lib/data";
export const dynamic = "force-dynamic";
export default async function IncidentsPage() {
  const { items, error } = await load<Incident[]>("/api/v1/incidents?limit=100");
  return <><h1>Incidents</h1><p className="muted">Live API. Latest 100 records, no synthetic fallback.</p>{error && <p role="alert">{error}</p>}<div className="card"><table className="table"><thead><tr><th>Incident</th><th>Service</th><th>Severity</th><th>Status</th><th>Created</th></tr></thead><tbody>{items?.map(i => <tr key={i.id}><td><Link href={`/incidents/${encodeURIComponent(i.id)}`}>{i.title}</Link></td><td>{i.service}</td><td>{i.severity}</td><td>{i.status}</td><td>{i.created_at}</td></tr>)}</tbody></table>{items?.length === 0 && <p>No incidents.</p>}</div></>;
}
