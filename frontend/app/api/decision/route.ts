import { boundedText } from "@/lib/body";
import { NextRequest, NextResponse } from "next/server";
import { consoleOrigin, session, validCsrf } from "@/lib/session";
import { gateway } from "@/lib/gateway";
import { identifier } from "@/lib/data";
export const runtime="nodejs";
export async function POST(request:NextRequest) {
  const current=session(), origin=consoleOrigin();
  if(!current || request.headers.get("origin")!==origin) return new NextResponse("Forbidden",{status:403});
  const raw=await boundedText(request, 4096);
  if(raw.length>4096)return new NextResponse("Too large",{status:413});
  const form=new URLSearchParams(raw), decision=form.get("decision")||"", note=form.get("note")||"";
  if(!validCsrf(current.csrf,form.get("csrf")||"") || !["approve","reject","defer"].includes(decision) || note.length>1000) return new NextResponse("Forbidden",{status:403});
  try {
    await gateway(`/api/v1/incidents/${identifier(form.get("id")||"")}/${decision}`,current.token,{actor:"console-operator",note});
    return NextResponse.redirect(new URL("/approvals?done=1",origin),303);
  } catch {return NextResponse.redirect(new URL("/approvals?error=1",origin),303);}
}
