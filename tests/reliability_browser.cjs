// Run with the disposable integration_miniapp.py --admin --serve fixture.
const {chromium} = require('playwright');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const values = {auth_date:String(Math.floor(Date.now()/1000)), user:JSON.stringify({id:42, first_name:'Fixture'})};
const secret = crypto.createHmac('sha256','WebAppData').update('123456:local-test-token-not-for-production').digest();
values.hash = crypto.createHmac('sha256',secret).update(Object.keys(values).sort().map(k=>k+'='+values[k]).join('\n')).digest('hex');
(async()=>{
 const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try {
  const context=await browser.newContext({viewport:{width:390,height:844}});
  await context.route('https://telegram.org/**',r=>r.abort());
  await context.addInitScript(raw=>{window.Telegram={WebApp:{initData:raw,ready(){},expand(){},setHeaderColor(){},setBackgroundColor(){}}};},new URLSearchParams(values).toString());
  let catalogRequests=0, invoiceRequests=0, catalogSample;
  await context.route('**/api/catalog?**',async route=>{
   catalogRequests++;
   const response=await route.fetch(), original=await response.json(), page=Number(new URL(route.request().url()).searchParams.get('page'));
   const sample=original.items[0] || catalogSample; assert(sample); catalogSample=sample;
   const items=Array.from({length:24},(_,i)=>({...sample,id:1000+page*24+i,product_id:'SBA-'+(1000+page*24+i),name:'Fixture '+(1000+page*24+i),in_cart:false,favorite:false}));
   await route.fulfill({response,json:{...original,items,has_more:page===0}});
  });
  await context.route('**/api/products/*',async route=>{
   const id=Number(route.request().url().split('/').at(-1));
   await new Promise(resolve=>setTimeout(resolve,id===1000?350:30));
   await route.fulfill({status:200,json:{id,name:'Product '+id,product_id:'SBA-'+id,category:'us',price:'100',characteristics:{warranty_hours:24}}});
  });
  await context.route('**/api/payment-methods',r=>r.fulfill({status:200,json:{items:[{id:'crypto',name:'Fixture Pay',enabled:true}]}}));
  await context.route('**/api/invoices',r=>{invoiceRequests++;return r.fulfill({status:502,contentType:'text/html',body:'<html>gateway fixture</html>'});});
  const p=await context.newPage(), errors=[];
  p.on('pageerror',e=>errors.push(e.message));
  await p.goto('http://127.0.0.1:8085'); await p.waitForSelector('.account-card');
  await p.locator('#load-more').click(); await p.waitForFunction(()=>document.querySelectorAll('.account-card').length===48);
  const before=catalogRequests;
  await p.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));
  await p.waitForFunction(()=>document.querySelector('#sync-state').textContent.includes('Баланс обновлён'));
  assert.equal(await p.locator('.account-card').count(),48);
  assert.equal(catalogRequests,before,'Background sync must preserve appended pages');
  await p.evaluate(()=>{
   document.querySelector('[data-features="1000"]').click();
   document.querySelector('[data-features="1001"]').click();
  });
  await p.waitForFunction(()=>document.querySelector('#dialog-title')?.textContent==='Product 1001');
  await p.waitForTimeout(450);
  assert.equal(await p.locator('#dialog-title').textContent(),'Product 1001','Late response must not replace newer dialog');
  await p.locator('#close-dialog').click();
  await p.locator('[data-topup]').first().click();await p.waitForSelector('#create-invoice');await p.locator('#create-invoice').click();
  await p.waitForSelector('#dialog-error:visible');
  assert((await p.locator('#dialog-error').textContent()).includes('Сервер вернул неполный ответ'));
  assert.equal(invoiceRequests,1,'Failed invoice creation must not be silently retried');
  assert.equal(await p.locator('#create-invoice').isEnabled(),true);
  assert.deepEqual(errors,[]);
  assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  console.log('PASS: mobile pagination survives sync, stale product replies are ignored, gateway errors are readable and payments are not retried');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
