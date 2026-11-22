import { load } from "@/lib/data";
export const dynamic="force-dynamic";
export default async function Postmortems(){
 const {items,error}=await load<Record<string,unknown>[]>("/api/v1/postmortems");
 return <><h1>Postmortems</h1><p className="muted">Reports from recorded incident closures. Research intervals remain null when ground-truth timing is absent.</p>{error&&<p role="alert">{error}</p>}{items?.map((p,n)=><div className="card" key={n} style={{marginBottom:16}}><span className="badge">AI · evidence-cited</span><h2>{String(p.title||p.incident_id||"Incident report")}</h2><pre>{JSON.stringify(p,null,2)}</pre></div>)}{items?.length===0&&<div className="card">No closed-incident reports yet.</div>}</>;
}
