import { identifier, load } from "@/lib/data";
export const dynamic="force-dynamic";
export default async function Audit({searchParams}:{searchParams:{incident?:string}}){
 const id=searchParams.incident?identifier(searchParams.incident):"";
 const {items,error}=await load<Record<string,unknown>[]>(`/api/v1/audit?limit=200${id?`&incident_id=${id}`:""}`);
 return <><h1>Audit log</h1><p className="muted">Latest 200 append-only records. Filter by incident to inspect decisions and actions.</p><form><label htmlFor="incident">Incident ID</label><input id="incident" name="incident" defaultValue={searchParams.incident||""} maxLength={160}/><button>Filter</button></form>{error&&<p role="alert">{error}</p>}<div className="card" style={{marginTop:20}}>{items?.map((r,n)=><details key={n}><summary>{String(r.at)} / {String(r.action)} / {String(r.actor)}</summary><pre>{JSON.stringify(r,null,2)}</pre></details>)}{items?.length===0&&<p>No matching audit records.</p>}</div></>;
}
