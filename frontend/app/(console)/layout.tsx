import { ReactNode } from "react";
import { redirect } from "next/navigation";
import { session } from "@/lib/session";
import { Nav } from "../nav";
import { Refresh } from "./refresh";

export const dynamic = "force-dynamic";
export default function ConsoleLayout({ children }: { children: ReactNode }) {
  const current = session();
  if (!current) redirect("/login");
  return <div className="shell">
    <aside className="side"><div className="brand">Aegis<span>SRE</span></div>
      <p>SRE + DevSecOps control plane</p><Nav />
      <form method="post" action="/api/logout"><input type="hidden" name="csrf" value={current.csrf} /><button>Sign out</button></form>
    </aside><main className="main"><Refresh />{children}</main>
  </div>;
}
