import { createCipheriv, createDecipheriv, createHash, randomBytes, timingSafeEqual } from "node:crypto";

export const COOKIE = "aegis_session";
export const MAX_AGE = 8 * 60 * 60;

type Session = { token: string; expires: number; csrf: string };

function key(): Buffer {
  const value = process.env.AEGIS_CONSOLE_SESSION_SECRET;
  if (!value || Buffer.byteLength(value) < 32) throw new Error("Console session encryption is not configured");
  return createHash("sha256").update(value).digest();
}

export function seal(token: string): string {
  if (!token || Buffer.byteLength(token) > 512) throw new Error("Invalid operator token");
  const nonce = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key(), nonce);
  const body: Session = { token, expires: Date.now() + MAX_AGE * 1000, csrf: randomBytes(24).toString("hex") };
  const encrypted = Buffer.concat([cipher.update(JSON.stringify(body)), cipher.final()]);
  return Buffer.concat([nonce, cipher.getAuthTag(), encrypted]).toString("base64url");
}

export function unseal(value: string | undefined): Session | null {
  try {
    if (!value || value.length > 2048) return null;
    const bytes = Buffer.from(value, "base64url");
    if (bytes.length < 29) return null;
    const decipher = createDecipheriv("aes-256-gcm", key(), bytes.subarray(0, 12));
    decipher.setAuthTag(bytes.subarray(12, 28));
    const body = JSON.parse(Buffer.concat([decipher.update(bytes.subarray(28)), decipher.final()]).toString());
    if (typeof body.token !== "string" || !body.token || body.token.length > 512 ||
        typeof body.expires !== "number" || body.expires <= Date.now() || body.expires > Date.now() + MAX_AGE * 1000 ||
        typeof body.csrf !== "string" || !/^[a-f0-9]{48}$/.test(body.csrf)) return null;
    return body as Session;
  } catch { return null; }
}

export function validCsrf(expected: string, supplied: string): boolean {
  const a = Buffer.from(expected), b = Buffer.from(supplied);
  return a.length === b.length && timingSafeEqual(a, b);
}

export function consoleOrigin(): string {
  const value = process.env.AEGIS_CONSOLE_ORIGIN || "http://localhost:3030";
  const parsed = new URL(value);
  if (!["http:", "https:"].includes(parsed.protocol) || parsed.username || parsed.password ||
      parsed.pathname !== "/" || parsed.search || parsed.hash) throw new Error("Invalid console origin");
  return parsed.origin;
}
