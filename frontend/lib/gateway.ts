export class ApiError extends Error {
  constructor(public status: number) { super(`Upstream request failed (${status})`); }
}

export function gatewayOrigin(): string {
  const value = process.env.AEGIS_CONSOLE_GATEWAY_URL || "http://127.0.0.1:8080";
  const parsed = new URL(value);
  if (!["http:", "https:"].includes(parsed.protocol) || parsed.username || parsed.password ||
      parsed.pathname !== "/" || parsed.search || parsed.hash) throw new Error("Invalid gateway origin");
  return parsed.origin;
}

export async function gateway<T>(path: string, token: string, body?: unknown): Promise<T> {
  // Paths are chosen by server code, never a caller-provided URL or redirect.
  if (!path.startsWith("/api/v1/") || path.includes("..") || /[\\\r\n]/.test(path)) throw new Error("Invalid API path");
  const response = await fetch(gatewayOrigin() + path, {
    method: body === undefined ? "GET" : "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store", redirect: "error", signal: AbortSignal.timeout(140000),
  });
  if (!response.ok) throw new ApiError(response.status);
  const reader = response.body?.getReader();
  if (!reader) throw new Error("Missing API response");
  const chunks: Uint8Array[] = []; let size = 0;
  try {
    while (true) {
      const {value, done} = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 2_000_000) { await reader.cancel(); throw new Error("Oversized API response"); }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  return JSON.parse(Buffer.concat(chunks).toString("utf8")) as T;
}
