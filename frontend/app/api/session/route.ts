import { boundedText } from "@/lib/body";
import { NextRequest, NextResponse } from "next/server";
import { COOKIE, MAX_AGE, consoleOrigin, seal } from "@/lib/session";
import { gateway } from "@/lib/gateway";

export const runtime = "nodejs";

export async function POST(request: NextRequest) {
  try {
    const origin = consoleOrigin();
    if (request.headers.get("origin") !== origin) return new NextResponse("Origin rejected", { status: 403 });
    if (Number(request.headers.get("content-length")) > 4096) return new NextResponse("Too large", { status: 413 });
    const raw = await boundedText(request, 4096);
    if (raw.length > 4096) return new NextResponse("Too large", { status: 413 });
    const data = new URLSearchParams(raw);
    const token = data.get("token") || "";
    if (!token || token.length > 512) return NextResponse.redirect(new URL("/login?error=1", origin), 303);
    await gateway("/api/v1/autonomy", token);
    const response = NextResponse.redirect(new URL("/", origin), 303);
    response.cookies.set(COOKIE, seal(token), { httpOnly: true, sameSite: "strict", secure: origin.startsWith("https:"), maxAge: MAX_AGE, path: "/" });
    response.headers.set("Cache-Control", "no-store");
    return response;
  } catch { return NextResponse.redirect(new URL("/login?error=1", consoleOrigin()), 303); }
}
