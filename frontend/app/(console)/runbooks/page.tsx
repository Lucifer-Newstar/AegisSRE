import { identifier, load } from "@/lib/data";
import { RunbookText } from "./text";
export const dynamic="force-dynamic";
export default async function Runbooks({searchParams}:{searchParams:{id?:string}}){
 const list=await load<Record<string,unknown>[]>("/api/v1/runbooks");
 const selected=searchParams.id?await load<Record<string,unknown>>(`/api/v1/runbooks/${identifier(searchParams.id)}`):null;
 return <><h1>Runbooks</h1><p className="muted">Reference material, not proof that a diagnosis is correct or permission to act.</p>{list.error&&<p role="alert">{list.error}</p>}<div className="columns"><div className="card">{list.items?.map(r=><p key={String(r.id)}><a href={`/runbooks?id=${encodeURIComponent(String(r.id))}`}>{String(r.title||r.id)}</a></p>)}{list.items?.length===0&&<p>No indexed runbooks.</p>}</div><div className="card">{selected?.error?<p role="alert">{selected.error}</p>:selected?.items?<><h2>{String(selected.items.title||selected.items.id)}</h2><p className="muted">Source: {String(selected.items.source||"Not supplied")}</p><RunbookText content={String(selected.items.content||"")} /></>:<p>Select a runbook.</p>}</div></div></>;
}
