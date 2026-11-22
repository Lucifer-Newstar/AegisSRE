import { boundedText } from "@/lib/body";
import { NextRequest, NextResponse } from "next/server";
import { session, consoleOrigin, validCsrf } from "@/lib/session";
import { gateway } from "@/lib/gateway";
export const runtime="nodejs";
export async function POST(request:NextRequest){
 const current=session();
 if(!current||request.headers.get("origin")!==consoleOrigin())return NextResponse.json({error:"Forbidden"},{status:403});
 const raw=await boundedText(request, 4096);
 if(raw.length>4096)return NextResponse.json({error:"Too large"},{status:413});
 try{
 const body=JSON.parse(raw);
 if(!validCsrf(current.csrf,String(body.csrf||""))||typeof body.question!=="string"||!body.question.trim()||body.question.length>2000||typeof body.service!=="string"||!/^[a-z0-9-]{1,63}$/.test(body.service))return NextResponse.json({error:"Invalid request"},{status:422});
 const result=await gateway("/api/v1/ask",current.token,{service:body.service,question:body.question});
 return NextResponse.json(result,{headers:{"Cache-Control":"no-store"}});
 }catch{return NextResponse.json({error:"Ask request failed. No answer was invented."},{status:503});}
}
