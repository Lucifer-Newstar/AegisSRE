import {chromium} from 'playwright';
import fs from 'node:fs';
const output=process.env.AEGIS_VISUAL_OUTPUT;
if(!output||process.env.GITHUB_ACTIONS!=='true')throw new Error('Owned CI fixture output required');
fs.mkdirSync(output,{recursive:true});
const browser=await chromium.launch({headless:true});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 await page.goto('http://127.0.0.1:13000/login');
 await page.getByPlaceholder('email or username').fill('admin');
 await page.getByPlaceholder('password').fill('ci-disposable-grafana');
 await page.getByRole('button',{name:'Log in',exact:true}).click();
 await page.waitForURL(url=>!url.pathname.endsWith('/login'));
 await page.goto('http://127.0.0.1:13000/d/aegisshop-slo');
 await page.getByText('Measurement limits',{exact:true}).waitFor();
 await page.waitForTimeout(3000);
 await page.screenshot({path:output+'/grafana-slo.png',fullPage:true});
 console.log('Actual owned-kind Grafana pixels captured for separate inspection. Screenshot alone does not establish metric accuracy.');
}finally{await browser.close();}
