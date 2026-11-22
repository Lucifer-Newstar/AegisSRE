import { Envelope, Incident, identifier, load } from "@/lib/data";
import Link from "next/link";
export const dynamic = "force-dynamic";
export default async function ServiceDetail({params}:{params:{id:string}}) {
  const id=identifier(params.id);
  const [service, events, incidents] = await Promise.all([load<Record<string,unknown>>(`/api/v1/services/${id}`),load<Envelope[]>(`/api/v1/events?service=${id}&limit=200`),load<Incident[]>(`/api/v1/incidents?service=${id}&limit=100`)]);
  return <><h1>{String(service.items?.name || params.id)}</h1>{[service.error,events.error,incidents.error].filter(Boolean).map((e,n)=><p role="alert" key={n}>{e}</p>)}<div className="card"><h2>Registry and SLO configuration</h2><pre>{JSON.stringify(service.items,null,2)}</pre><p className="muted">Configured objectives are not measured availability or error-budget remaining.</p></div><h2>Observed telemetry</h2><p className="muted">Latest 200 persisted events. This is a bounded evidence table, not a complete 24-hour chart.</p><div className="card"><table className="table"><thead><tr><th>Time</th><th>Type / source</th><th>Evidence</th></tr></thead><tbody>{events.items?.map(e=><tr key={e.id}><td>{e.timestamp}</td><td>{e.type} / {e.source}</td><td><details><summary>{e.id}</summary><pre>{JSON.stringify(e,null,2)}</pre></details></td></tr>)}</tbody></table></div><h2>Incidents</h2>{incidents.items?.map(i=><p key={i.id}><Link href={`/incidents/${identifier(i.id)}`}>{i.title} / {i.status}</Link></p>)}</>;
}
