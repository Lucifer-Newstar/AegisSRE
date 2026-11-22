import { Incident, load } from "@/lib/data";
import { session } from "@/lib/session";
import Link from "next/link";
export const dynamic="force-dynamic";
export default async function Approvals({searchParams}:{searchParams:{done?:string;error?:string}}){
 const {items,error}=await load<Incident[]>("/api/v1/incidents?limit=100"), current=session();
 const pending=(items||[]).filter(i=>["pending","deferred"].includes(i.approval)&&!["closed","escalated"].includes(i.status));
 return <><h1>Approvals</h1><p className="muted">Policy decides execution. These decisions are audited by the authenticated gateway principal. Approving does not itself execute an action.</p>{error&&<p role="alert">{error}</p>}{searchParams.done&&<p role="status">Decision recorded.</p>}{searchParams.error&&<p role="alert">Decision was not confirmed. Refresh before retrying.</p>}{pending.map(i=><div className="card" key={i.id} style={{marginBottom:16}}><Link href={`/incidents/${encodeURIComponent(i.id)}`}><h2>{i.title}</h2></Link><p>{i.plan.action} / {i.plan.target} / {i.plan.risk} risk / {i.plan.executor}</p><p>{i.plan.impact||"No impact estimate supplied"}</p><p>{i.plan.reason}</p><form method="post" action="/api/decision"><input type="hidden" name="csrf" value={current?.csrf}/><input type="hidden" name="id" value={i.id}/><label htmlFor={`note-${i.id}`}>Reason (optional)</label><input id={`note-${i.id}`} name="note" maxLength={1000}/><div className="actions">{["approve","reject","defer"].map(d=><button key={d} name="decision" value={d} disabled={d==="approve"&&i.plan.risk==="forbidden"}>{d}</button>)}</div></form></div>)}{!pending.length&&!error&&<div className="card">No pending decisions in the latest 100 incidents.</div>}</>;
}
