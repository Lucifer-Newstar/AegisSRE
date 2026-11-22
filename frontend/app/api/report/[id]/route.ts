import { NextResponse } from "next/server";
import { session } from "@/lib/session";
import { gateway, ApiError } from "@/lib/gateway";
import { identifier } from "@/lib/data";
import { reportMarkdown, Report } from "@/lib/report";
export const runtime="nodejs";
export const dynamic="force-dynamic";
export async function GET(_request:Request,{params}:{params:{id:string}}){
 const current=session();if(!current)return new NextResponse("Authentication required",{status:401});
 try{
 const id=identifier(params.id);const p=await gateway<Report>(`/api/v1/postmortems/${id}`,current.token); return new NextResponse(reportMarkdown(p),{headers:{"Content-Type":"text/markdown; charset=utf-8","Content-Disposition":`attachment; filename="aegis-${id}.md"`,"Cache-Control":"private, no-store","X-Content-Type-Options":"nosniff"}});
 }catch(error){return new NextResponse("Report unavailable. No report substituted.",{status:error instanceof ApiError&&error.status===404?404:503,headers:{"Cache-Control":"no-store"}});}
}
