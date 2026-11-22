import { redirect } from "next/navigation";
import { session } from "./session";
import { ApiError, gateway } from "./gateway";
import type { Deployment, ServiceInfo, ServiceStatus } from "./types";

export type Incident = {
  id: string; service: string; environment: string; title: string; severity: string; status: string;
  created_at: string; updated_at: string; approval: string; approved_by: string | null;
  resolved_at: string | null; fault_started_at: string | null; executed_at: string | null;
  execution_output: string | null; evidence_ids: string[];
  signals: { metric: string; observed: number; baseline_mean: number; z_score: number; event_id: string }[];
  analysis: { engine: string; summary: string; confidence: string; caveat: string; hypotheses: Record<string, unknown>[]; evidence_ids: string[] };
  plan: { action: string; target: string; risk: string; executor: string; impact: string; reason: string; requires_approval: boolean; reversible: boolean; revision?: string };
  audit: { at: string; action: string; actor: string; detail: string }[];
};
export type Envelope = { id: string; timestamp: string; type: string; source: string; service: string; payload: Record<string, unknown>; trace_id?: string };
export type Result<T> = { items: T; error: string | null };

export async function load<T>(path: string): Promise<Result<T | null>> {
  const current = session();
  if (!current) redirect("/login");
  try { return { items: await gateway<T>(path, current.token), error: null }; }
  catch (error) {
    if (error instanceof ApiError && error.status === 401) redirect("/login?error=1");
    return { items: null, error: error instanceof ApiError ? `API unavailable (${error.status}). No data substituted.` : "API connection failed. No data substituted." };
  }
}
export async function loadServices() {
  const result = await load<Record<string, unknown>[]>("/api/v1/services");
  const items: ServiceInfo[] = (result.items || []).map(row => ({
    id: String(row.id), name: String(row.name), url: String(row.url), version: String(row.version || "unknown"),
    status: (["healthy", "degraded", "unhealthy", "unknown"].includes(String(row.status)) ? row.status : "unknown") as ServiceStatus,
  }));
  return { items, error: result.error, source: "live" as const };
}
export async function loadDeployments() {
  const result = await load<Record<string, unknown>[]>("/api/v1/deployments?limit=100");
  const items: Deployment[] = (result.items || []).map(row => ({ eventId: String(row.event_id), service: String(row.service), revision: String(row.revision), status: row.status as Deployment["status"], storedAt: String(row.stored_at) }));
  return { items, error: result.error, source: "live" as const };
}
export function identifier(value: string): string {
  if (!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(value)) throw new Error("Invalid identifier");
  return encodeURIComponent(value);
}
