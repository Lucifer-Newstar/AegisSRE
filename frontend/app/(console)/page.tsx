import Link from "next/link";
import { Incident, load, loadServices } from "@/lib/data";
export const dynamic = "force-dynamic";
export default async function CommandCenterPage() {
  const [services, incidents, mode] = await Promise.all([loadServices(), load<Incident[]>("/api/v1/incidents?limit=100"), load<{ mode: string; executor: string }>("/api/v1/autonomy")]);
  const rows = incidents.items || [], open = rows.filter(i => !["closed", "escalated"].includes(i.status));
  return <><div className="topbar"><div><p className="muted">OPERATIONS / LIVE CONTROL PLANE</p><h1>Command Center</h1></div><span className="mode">{mode.items?.mode || "UNKNOWN"} / {mode.items?.executor || "unknown"}</span></div>
    {[services.error, incidents.error, mode.error].filter(Boolean).map((e, i) => <p role="alert" key={i}>{e}</p>)}
    <div className="grid"><div className="card"><h3>Services healthy</h3><div className="val">{services.error ? "Unknown" : `${services.items.filter(s => s.status === "healthy").length}/${services.items.length}`}</div></div><div className="card"><h3>Active incidents</h3><div className="val">{incidents.error ? "Unknown" : open.length}</div></div><div className="card"><h3>Research MTTD</h3><div className="val">Not measured</div></div><div className="card"><h3>Research MTTR</h3><div className="val">Not measured</div></div></div>
    <div className="card"><h2>Service health</h2><div className="grid">{services.items.map(s => <Link className="card" key={s.id} href={`/services/${encodeURIComponent(s.id)}`}><h3>{s.name}</h3><span className={`pill ${s.status}`}>{s.status}</span><p className="muted">{s.version}</p></Link>)}</div>{!services.error && !services.items.length && <p>No services registered.</p>}</div>
    <div className="card" style={{ marginTop: 20 }}><h2>Incident feed</h2><table className="table"><thead><tr><th>Incident</th><th>Service</th><th>Status</th><th>Severity</th></tr></thead><tbody>{rows.map(i => <tr key={i.id}><td><Link href={`/incidents/${encodeURIComponent(i.id)}`}>{i.title}</Link></td><td>{i.service}</td><td>{i.status}</td><td><span className={`pill ${i.severity}`}>{i.severity}</span></td></tr>)}</tbody></table>{!rows.length && !incidents.error && <p>No incidents in the current API window.</p>}</div>
    <p><Link href="/ask">Ask Aegis about the evidence →</Link></p><p className="muted">Limited to the latest 100 incidents. Missing ground-truth timing is never shown as zero.</p></>;
}
