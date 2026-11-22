import { Fragment } from "react";
// Text-only Markdown subset. Raw HTML, images, links and directives never run.
export function RunbookText({content}:{content:string}){
 let code=false;let buffer:string[]=[];const nodes:React.ReactNode[]=[];
 for(const [n,line] of content.split("\n").entries()){
  if(line.startsWith("```")){if(code){nodes.push(<pre className="evidence" key={n}>{buffer.join("\n")}</pre>);buffer=[];}code=!code;continue;}
  if(code){buffer.push(line);continue;}
  if(line.startsWith("### "))nodes.push(<h3 key={n}>{line.slice(4)}</h3>);
  else if(line.startsWith("## "))nodes.push(<h2 key={n}>{line.slice(3)}</h2>);
  else if(line.startsWith("# "))nodes.push(<h2 key={n}>{line.slice(2)}</h2>);
  else if(/^[-*] /.test(line))nodes.push(<p key={n}>• {line.slice(2)}</p>);
  else nodes.push(<p key={n}>{line||" "}</p>);
 }
 if(buffer.length)nodes.push(<pre className="evidence" key="remaining">{buffer.join("\n")}</pre>);
 return <Fragment>{nodes}</Fragment>;
}
