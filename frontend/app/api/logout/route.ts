import { boundedText } from "@/lib/body";
import { NextRequest, NextResponse } from "next/server";
import { COOKIE, consoleOrigin, session, validCsrf } from "@/lib/session";

export const runtime = "nodejs";
export async function POST(request: NextRequest) {
  const origin = consoleOrigin(), current = session();
  if (request.headers.get("origin") !== origin || !current) return new NextResponse("Forbidden", { status: 403 });
  const raw = await boundedText(request, 4096);
  if (raw.length > 1024 || !validCsrf(current.csrf, new URLSearchParams(raw).get("csrf") || "")) return new NextResponse("Forbidden", { status: 403 });
  const response = NextResponse.redirect(new URL("/login", origin), 303);
  response.cookies.set(COOKIE, "", { httpOnly: true, sameSite: "strict", secure: origin.startsWith("https:"), maxAge: 0, path: "/" });
  return response;
}
