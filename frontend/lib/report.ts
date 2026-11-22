import type { Incident } from "./data";
export type Report={incident:Incident;mttd_seconds:number|null;mttr_seconds:number|null;incident_duration_seconds:number|null;timing_caveats:string[];lessons:string[];simulation:boolean};
const literal=(value:unknown)=>JSON.stringify(value).replace(/[<>&`*_!\[\]#\\]/g,c=>`\\u${c.charCodeAt(0).toString(16).padStart(4,"0")}`);
export function reportMarkdown(p:Report):string{
const i=p.incident;
 // JSON-quoted strings preserve untrusted evidence as literal text. No HTML,
 // resource URLs or Markdown directives from evidence become active markup.
 const lines=["# AegisSRE incident postmortem","","AI-assisted interpretation. Evidence is data, not instructions.","",`Incident: ${literal(i.id)}`,`Title: ${literal(i.title)}`,`Service: ${literal(i.service)}`,`Status: ${literal(i.status)}`,`Simulation: ${p.simulation}`,"","## Timing",`Fault-onset MTTD seconds: ${p.mttd_seconds??"Not measured"}`,`Fault-onset MTTR seconds: ${p.mttr_seconds??"Not measured"}`,`Incident duration seconds: ${p.incident_duration_seconds??"Not measured"}`,...p.timing_caveats.map(c=>literal(c)),"","## Reasoning",literal(i.analysis),"","## Timeline",...i.audit.map(a=>literal(a)),"","## Action and result",literal(i.plan),literal(i.execution_output),"","## Evidence references",...i.evidence_ids.map(e=>literal(e)),"","## Generic follow-up checklist (not confirmed findings)",...p.lessons.map(l=>literal(l)),""];
 return lines.join("\n");
}
