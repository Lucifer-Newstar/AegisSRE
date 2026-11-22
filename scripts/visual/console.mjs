import {chromium} from 'playwright';
import fs from 'node:fs';
const output=process.env.AEGIS_VISUAL_OUTPUT;
if(!output||process.env.GITHUB_ACTIONS!=='true'||process.env.AEGIS_API_TOKEN!=='ci-disposable-runtime-token')throw new Error('Owned disposable CI fixture required');
fs.mkdirSync(output,{recursive:true});
const browser=await chromium.launch({headless:true});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 await page.goto('http://localhost:3030/');
 await page.waitForURL('**/login');
 await page.fill('input[name=token]',process.env.AEGIS_API_TOKEN);
 await page.click('button[type=submit]');
 await page.waitForURL('http://localhost:3030/');
 await page.getByRole('heading',{name:'Command Center',exact:true}).waitFor();
 for(const [route,label] of [['/','overview'],['/services/catalog-service','catalog'],['/approvals','approvals'],['/postmortems','postmortems'],['/runbooks','runbooks'],['/deployments','deployments']]){
  await page.goto('http://localhost:3030'+route);
  await page.locator('h1').waitFor();
  if((await page.content()).includes(process.env.AEGIS_API_TOKEN))throw new Error('Fixture token appeared in page data');
  const failure=await page.locator('[role=alert]').allTextContents();
  if(failure.some(t=>t.includes('API unavailable')||t.includes('No data substituted')))throw new Error('Visible page API failure on '+route);
  await page.screenshot({path:output+'/console-'+label+'.png',fullPage:true});
 }
 console.log('Actual Next console pixels captured from the owned platform APIs; no decisions, actions or model calls. Separate pixel inspection required.');
}finally{await browser.close();}
