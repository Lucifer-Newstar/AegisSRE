// Approval interaction proof, not permission to execute or acceptance accuracy.
import {chromium} from 'playwright';
import fs from 'node:fs';
const output=process.env.AEGIS_VISUAL_OUTPUT,token=process.env.AEGIS_API_TOKEN;
if(!output||process.env.GITHUB_ACTIONS!=='true'||token!=='ci-disposable-runtime-token')throw new Error('Owned disposable fixture required');
fs.mkdirSync(output,{recursive:true});
async function api(path,body){
 const response=await fetch('http://127.0.0.1:8080/api/v1'+path,{method:body?'POST':'GET',
  headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});
 if(!response.ok)throw new Error('API failure '+response.status);
 return await response.json();
}
const rows=await api('/incidents?service=ci-runtime');
if(rows.length!==1||rows[0].status!=='investigating')throw new Error('Unique investigating seeded fixture required');
const id=encodeURIComponent(rows[0].id);
// Reset only the seeded fixture's existing approval, not a natural incident.
const before=await api('/incidents/'+id+'/defer',{actor:'ignored-client-actor',note:'Prepare owned approval UI test; no execution'});
const browser=await chromium.launch({headless:true});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 await page.goto('http://localhost:3030/login');
 await page.fill('input[name=token]',token);await page.click('button[type=submit]');
 await page.waitForURL('http://localhost:3030/');
 await page.getByRole('heading',{name:'Command Center',exact:true}).waitFor();
 let clicks=0;
 await page.getByRole('link',{name:'Approvals',exact:true}).click();clicks++;
 const card=page.locator('div.card').filter({has:page.getByRole('heading',{name:before.title,exact:true})});
 await card.getByText(before.plan.reason,{exact:true}).waitFor();
 await card.getByText(before.plan.impact,{exact:true}).waitFor();
 const response=page.waitForResponse(r=>r.url().endsWith('/api/decision')&&r.request().method()==='POST');
 await card.getByRole('button',{name:'approve',exact:true}).click();clicks++;
 if((await response).status()!==303)throw new Error('Approval submit not confirmed');
 await page.getByRole('status').filter({hasText:'Decision recorded.'}).waitFor();
 const after=await api('/incidents/'+id);
 if(after.approval!=='approved'||after.approved_by!=='token:operator'||after.status!==before.status)throw new Error('Unexpected approval/state/actor');
 if(after.executed_at!==before.executed_at||JSON.stringify(after.plan)!==JSON.stringify(before.plan))throw new Error('Approval changed plan or executed action');
 if(after.audit.filter(a=>a.action==='remediation.approved').length!==before.audit.filter(a=>a.action==='remediation.approved').length+1)throw new Error('Approval audit count');
 if(clicks>3)throw new Error('Approval click budget exceeded');
 await page.screenshot({path:output+'/approval-confirmed.png',fullPage:true});
 fs.writeFileSync(output+'/approval-proof.json',JSON.stringify({
  authenticated_start:'command-center',clicks_to_approval:clicks,login_excluded:true,
  actual_form_submit:true,principal:after.approved_by,incident_id:after.id,
  status_and_plan_unchanged:true,no_execution:true,seeded_incident:true,
  not_fault_or_autonomy_acceptance:true},null,2));
}finally{await browser.close();}
