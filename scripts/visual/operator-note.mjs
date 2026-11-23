// Live browser form -> console CSRF handler -> gateway principal -> durable audit.
// Existing seeded integration incident only, not an inferred fault diagnosis.
import {chromium} from 'playwright';
import fs from 'node:fs';
const output=process.env.AEGIS_VISUAL_OUTPUT;
if(!output||process.env.GITHUB_ACTIONS!=='true'||process.env.AEGIS_API_TOKEN!=='ci-disposable-runtime-token')throw new Error('Owned disposable fixture required');
fs.mkdirSync(output,{recursive:true});
const headers={Authorization:'Bearer '+process.env.AEGIS_API_TOKEN};
async function api(path){
 const response=await fetch('http://127.0.0.1:8080/api/v1'+path,{headers});
 if(!response.ok)throw new Error('Live API read failed '+response.status);
 return await response.json();
}
const incidents=await api('/incidents?service=ci-runtime');
if(incidents.length!==1)throw new Error('Expected unique seeded integration incident');
const before=incidents[0],note='Owned browser form context, not verified telemetry';
const browser=await chromium.launch({headless:true});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 await page.goto('http://localhost:3030/login');
 await page.fill('input[name=token]',process.env.AEGIS_API_TOKEN);
 await page.click('button[type=submit]');
 await page.waitForURL('http://localhost:3030/');
 await page.goto('http://localhost:3030/incidents/'+encodeURIComponent(before.id));
 await page.getByRole('heading',{name:'Operator context',exact:true}).waitFor();
 const forbidden=await page.request.post('http://localhost:3030/api/incident-note',{
  headers:{Origin:'https://not-this-console.invalid'},form:{id:before.id,note}});
 if(forbidden.status()!==403)throw new Error('Cross-origin note accepted');
 const invalid=await page.request.post('http://localhost:3030/api/incident-note',{
  headers:{Origin:'http://localhost:3030'},form:{id:before.id,note,csrf:'wrong'}});
 if(invalid.status()!==422)throw new Error('Invalid CSRF note accepted');
 await page.getByLabel('Add context',{exact:true}).fill(note);
 const response=page.waitForResponse(r=>r.url().endsWith('/api/incident-note')&&r.request().method()==='POST');
 await page.getByRole('button',{name:'Record note',exact:true}).click();
 if((await response).status()!==303)throw new Error('Note form did not confirm');
 await page.waitForURL('**/incidents/'+encodeURIComponent(before.id));
 const after=await api('/incidents/'+encodeURIComponent(before.id));
 const records=after.audit.filter(a=>a.action==='operator.note'&&a.detail===note);
 if(records.length!==1||records[0].actor!=='token:operator')throw new Error('Note audit actor/count mismatch');
 for(const key of ['status','approval','approved_by','plan','undo']){
  if(JSON.stringify(before[key])!==JSON.stringify(after[key]))throw new Error('Note changed '+key);
 }
 await page.getByText(note,{exact:true}).waitFor();
 await page.screenshot({path:output+'/operator-note-submitted.png',fullPage:true});
 fs.writeFileSync(output+'/operator-note-proof.json',JSON.stringify({
  actual_browser_submit:true,principal:records[0].actor,incident_id:after.id,
  cross_origin_status:403,invalid_csrf_status:422,note_count:records.length,
  state_approval_plan_undo_unchanged:true,not_fault_acceptance:true},null,2));
 console.log('Live operator note form persisted once with gateway actor; CSRF/origin blocked and action state unchanged.');
}finally{await browser.close();}
