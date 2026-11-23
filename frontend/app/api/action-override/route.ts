import { boundedText } from "@/lib/body";
import { NextRequest, NextResponse } from "next/server";
import { consoleOrigin, session, validCsrf } from "@/lib/session";
import { gateway } from "@/lib/gateway";
import { identifier } from "@/lib/data";
export const runtime="nodejs";
export async function POST(request:NextRequest) {
 const current=session(),origin=consoleOrigin();
 if(!current||request.headers.get("origin")!==origin)return new NextResponse("Forbidden",{status:403});
 const raw=await boundedText(request,4096);if(raw.length>4096)return new NextResponse("Too large",{status:413});
 const form=new URLSearchParams(raw),operation=form.get("operation")||"",note=form.get("note")||"";
 if(!validCsrf(current.csrf,form.get("csrf")||"")||!["cancel","undo-scale"].includes(operation)||note.length>1000)return new NextResponse("Forbidden",{status:403});
 let id:string;try{id=identifier(form.get("id")||"");}catch{return new NextResponse("Invalid incident",{status:422});}
 try{await gateway(`/api/v1/actions/${id}/${operation}`,current.token,{actor:"console-operator",note});}
 catch{return new NextResponse("Override not confirmed. Refresh and inspect the audit before retrying.",{status:502});}
 return NextResponse.redirect(new URL(`/incidents/${id}`,origin),303);
}
