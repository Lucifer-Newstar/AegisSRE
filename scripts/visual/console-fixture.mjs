import http from 'node:http';
import {spawn} from 'node:child_process';
import {chromium} from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const output=process.env.AEGIS_VISUAL_OUTPUT||'/tmp/aegis-console-visual';fs.mkdirSync(output,{recursive:true});
const origin='http://127.0.0.1:3030';
const incident={id:'fixture-closed',title:'Fixture dependency failure, not real telemetry',service:'catalog-service',environment:'dev',severity:'sev2',status:'closed',created_at:'2026-11-22T20:00:00Z',resolved_at:'2026-11-22T20:02:00Z',fault_started_at:null,approval:'approved',analysis:{engine:'fixture',summary:'Synthetic dependency evidence for UI review only.',confidence:'low',caveat:'Not a real diagnosis',hypotheses:[],evidence_ids:[]},plan:{action:'restart',target:'catalog-service',risk:'low',executor:'simulation',reason:'Fixture action',impact:'No actual action',reversible:true},audit:[{at:'2026-11-22T20:00:00Z',actor:'fixture',action:'opened',detail:'Synthetic visual fixture'},{at:'2026-11-22T20:02:00Z',actor:'fixture',action:'closed',detail:'Synthetic recovery'}],evidence_ids:[],signals:[],execution_output:'Simulation only'};
const report={incident,mttd_seconds:null,mttr_seconds:null,incident_duration_seconds:120,timing_caveats:['Independent onset missing, research timing not measured.'],lessons:['Confirm the probable cause with an operator.'],simulation:true};
const fixture=http.createServer((req,res)=>{
 if(req.headers.authorization!=='Bearer ci-local-ui-fixture'){res.writeHead(401);res.end('{}');return;}
 let result={};
 if(req.url==='/api/v1/autonomy')result={mode:'recommend',executor:'simulation'};
 else if(req.url.startsWith('/api/v1/metric-history')){const metric=new URL(req.url,'http://fixture').searchParams.get('metric');const end=new Date(),start=new Date(end-86400000);result={metric,start:start.toISOString(),end:end.toISOString(),unit:({latency_p95:'seconds',error_rate:'ratio',request_rate:'requests/second',cpu_usage_percent:'percent',memory_bytes:'bytes'})[metric],bucket_seconds:300,status:'observed',missing_buckets:245,truncated:false,note:'Synthetic visual fixture only',points:Array.from({length:43},(_,i)=>({at:new Date(+end-13500000+i*300000).toISOString(),mean:0.1+Math.abs(Math.sin(i/4))*0.4,min:0.05,max:0.6,samples:20,evidence_id:'fixture:'+i}))};}
 else if(req.url==='/api/v1/services/catalog-service')result={id:'catalog-service',name:'AegisShop Catalog',version:'0.1.0',status:'unknown',availability_slo:0.999,latency_slo_seconds:0.5};
 else if(req.url.startsWith('/api/v1/services'))result=[{id:'catalog-service',name:'AegisShop Catalog',url:'http://catalog-service:9001',version:'0.1.0',status:'unknown'}];
 else if(req.url==='/api/v1/postmortems')result=[report];
 else if(req.url.startsWith('/api/v1/postmortems/'))result=report;
 else if(req.url==='/api/v1/runbooks')result=[{id:'runbook:fixture',title:'Fixture dependency checks'}];
 else if(req.url.startsWith('/api/v1/runbooks/'))result={id:'runbook:fixture',title:'Fixture dependency checks',source:'Synthetic visual fixture',content:'# Dependency checks\n## Observe first\n- Confirm actual health before acting\n```\ncurl /ready\n```\n<script>must remain literal</script>'};
 else if(req.url.includes('/context'))result={knowledge:[{document_id:'runbook:fixture',title:'Fixture dependency checks',kind:'runbook'}]};
 else if(req.url==='/api/v1/incidents/fixture-closed')result=incident;
 else if(req.url.startsWith('/api/v1/deployment-intelligence/risk'))result={items:[{deployment_id:'fixture-window',revision:'fixture-revision',observed_post_rollout:'bad',prediction:{probability:null,status:'insufficient_history',classification:'unknown',confirmed_outcomes:0,observed_bad:0,is_predeploy_prediction:false,model_version:'service-beta-binomial-v1',training_digest:'synthetic-visual-fixture',caveat:'Synthetic fixture, no trained history or prediction recall'}}],truncated:false};
 else if(req.url.startsWith('/api/v1/deployment-intelligence/summary'))result={identified_deployments:2,confirmed_bad:1,observed_healthy:0,unknown_outcomes:1,unidentified_or_unmapped_events:0,change_failure_rate:null,observed_finalized_rate:1,outcome_coverage:0.5,identified_failure_lower_bound:0.5,identified_failure_upper_bound:1,caveat:'Synthetic visual fixture. Unknown outcomes are not healthy.'};
 else if(req.url.startsWith('/api/v1/deployment-intelligence/rollouts'))result={rollouts:[{id:'fixture-window',revision:'fixture-revision',deployment_id:'fixture',started_at:'2026-11-22T20:00:00Z',phase:'succeeded',outcome:'bad',reason:'Synthetic observed anomaly, not real telemetry',ambiguous:false,flag_latency_seconds:null,source_event_ids:['fixture-deploy'],observation_ids:['fixture-anomaly'],incident_id:null}],truncated:false};
 else if(req.url.startsWith('/api/v1/deployments'))result=[{event_id:'fixture-deploy',service:'catalog-service',revision:'fixture-revision',status:'succeeded',stored_at:'2026-11-22T20:00:00Z'}];
 else if(req.url.startsWith('/api/v1/incidents'))result=[];
 else result=[];
 res.setHeader('Content-Type','application/json');res.end(JSON.stringify(result));
});
await new Promise(r=>fixture.listen(18880,'127.0.0.1',r));
const log=fs.openSync(path.join(output,'console-server.log'),'w');
const server=spawn(process.execPath,['node_modules/next/dist/bin/next','start','-p','3030'],{cwd:path.join(root,'frontend'),env:{...process.env,AEGIS_CONSOLE_SESSION_SECRET:'ci-local-disposable-session-secret-value',AEGIS_CONSOLE_GATEWAY_URL:'http://127.0.0.1:18880',AEGIS_CONSOLE_ORIGIN:origin,NEXT_TELEMETRY_DISABLED:'1'},stdio:['ignore',log,log]});
let browser;
try{
 for(let n=0;n<60;n++){try{await fetch(origin+'/login');break;}catch{await new Promise(r=>setTimeout(r,250));}}
 browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}});
 await page.goto(origin+'/');await page.waitForURL('**/login');
 await page.screenshot({path:path.join(output,'aegis-console-login.png'),fullPage:true});
 await page.fill('input[name=token]','ci-local-ui-fixture');await page.click('button[type=submit]');await page.waitForURL(origin+'/');
 await page.waitForSelector('h1');await page.screenshot({path:path.join(output,'aegis-console-overview.png'),fullPage:true});
 const html=await page.content();if(html.includes('ci-local-ui-fixture'))throw new Error('Token leaked into page');
 const cookies=await page.context().cookies();if(!cookies.some(c=>c.name==='aegis_session'&&c.httpOnly&&c.sameSite==='Strict'))throw new Error('Cookie protections absent');
 if(!html.includes('Not measured')||!html.includes('unknown'))throw new Error('Missing-data truth absent');
 await page.goto(origin+'/approvals');await page.screenshot({path:path.join(output,'aegis-console-approvals.png'),fullPage:true});
 await page.goto(origin+'/postmortems');await page.getByText('Fault-onset MTTD',{exact:true}).waitFor();await page.screenshot({path:path.join(output,'aegis-console-postmortem.png'),fullPage:true});
 const download=await page.request.get(origin+'/api/report/fixture-closed');const markdown=await download.text();if(download.status()!==200||!markdown.includes('Not measured')||!download.headers()['content-disposition'].includes('attachment'))throw new Error('Report export failure');
 await page.goto(origin+'/runbooks?id=runbook:fixture');await page.getByText('Observe first',{exact:true}).waitFor();await page.screenshot({path:path.join(output,'aegis-console-runbook.png'),fullPage:true});if(await page.locator('script').filter({hasText:'must remain literal'}).count())throw new Error('Runbook HTML active');
 await page.goto(origin+'/services/catalog-service');await page.getByText('24h observed metric history',{exact:true}).waitFor();await page.screenshot({path:path.join(output,'aegis-console-service-charts.png'),fullPage:true});
 await page.goto(origin+'/deployments');await page.getByText('Confirmed CFR,30d',{exact:true}).waitFor();if(!(await page.content()).includes('Unknown'))throw new Error('Unknown CFR replaced');await page.screenshot({path:path.join(output,'aegis-console-rollout-analytics.png'),fullPage:true});
 await page.goto(origin+'/incidents/fixture-closed');await page.getByText('Related runbooks',{exact:true}).waitFor();await page.getByRole('link',{name:'Fixture dependency checks'}).click();await page.waitForURL('**/runbooks?id=runbook%3Afixture');
 const forbidden=await page.request.post(origin+'/api/decision',{headers:{Origin:'https://not-this-console.invalid'},form:{id:'fixture',decision:'approve'}});if(forbidden.status()!==403)throw new Error('Cross-origin mutation accepted');
 console.log('Actual Next fixture pixels saved to '+output+'. Synthetic HTTP fixture only, not real telemetry. Login/cookie/CSRF, reports, export, incident-runbook navigation and sparse charts passed.');
}finally{if(browser)await browser.close();server.kill('SIGTERM');await new Promise(r=>server.on('exit',r));await new Promise(r=>fixture.close(r));fs.closeSync(log);}
