import { loadServices } from "@/lib/data";
import { session } from "@/lib/session";
import { AskForm } from "./form";
export const dynamic="force-dynamic";
export default async function Ask(){const services=await loadServices();return <><h1>Ask Aegis</h1><div className="card"><p>Ask Aegis is read-only. It exposes no write tools. Answers are interpretations tied to cited evidence, never permission to act.</p><p className="muted">The configured provider controls whether inference runs. Disabled inference is shown explicitly, never presented as a model answer.</p>{services.error&&<p role="alert">{services.error}</p>}<AskForm csrf={session()?.csrf||""} services={services.items}/></div></>;}
