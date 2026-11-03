// UI fixtures override only SpamBot results. Admin queue writes use the disposable real DB.
const {chromium}=require('playwright'),crypto=require('node:crypto'),assert=require('node:assert/strict'),fs=require('node:fs');
const values={auth_date:String(Math.floor(Date.now()/1000)),user:JSON.stringify({id:42,first_name:'Fixture'})};
const secret=crypto.createHmac('sha256','WebAppData').update('123456:local-test-token-not-for-production').digest();
values.hash=crypto.createHmac('sha256',secret).update(Object.keys(values).sort().map(k=>k+'='+values[k]).join('\n')).digest('hex');
(async()=>{
 const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  const context=await browser.newContext({viewport:{width:390,height:844}}),checked=new Date().toISOString();
  await context.route('https://telegram.org/**',r=>r.abort());
  await context.addInitScript(raw=>{window.Telegram={WebApp:{initData:raw,ready(){},expand(){},setHeaderColor(){},setBackgroundColor(){}}};},new URLSearchParams(values).toString());
  const labels={clear:'Ограничений не обнаружено',limited:'Есть ограничения',unknown:'Ответ не распознан'};
  await context.route('**/api/catalog?**',async route=>{
   const response=await route.fetch(),data=await response.json();
   data.items.forEach((item,i)=>{const status=i===0?'clear':i===1?'limited':'unknown';item.characteristics.spam_check={status,label:labels[status],checked_at:checked,running:false};});
   await route.fulfill({response,json:data});
  });
  await context.route('**/api/products/*',async route=>{
   const response=await route.fetch(),data=await response.json();
   data.characteristics.spam_check={status:'clear',label:labels.clear,checked_at:checked,running:false};
   await route.fulfill({response,json:data});
  });
  const p=await context.newPage(),errors=[];p.on('pageerror',e=>errors.push(e.message));
  await p.goto('http://127.0.0.1:8085');await p.waitForSelector('.spam-line');
  assert((await p.locator('.spam-line').first().innerText()).includes(labels.clear));
  assert((await p.locator('.spam-line').nth(1).innerText()).includes(labels.limited));
  fs.mkdirSync('/workspace/session-shope-previews',{recursive:true});
  await p.screenshot({path:'/workspace/session-shope-previews/spam-mobile.png',fullPage:true});
  await p.locator('[data-features]').first().click();await p.waitForSelector('#purchase-dialog[open]');
  const detail=await p.locator('#dialog-content').innerText();
  assert(detail.includes(labels.clear)&&detail.includes('@SpamBot')&&detail.includes('МСК'));
  await p.locator('#close-dialog').click();
  await p.locator('.mobile-nav [data-tab="profile"]').click();await p.locator('[data-open-admin]:visible').first().click();
  await p.waitForSelector('.admin-stats');await p.locator('[data-admin-tab="stock"]').click();await p.waitForSelector('[data-spam-check]');
  assert((await p.locator('.admin-table thead').innerText()).includes('Спамблок'));
  await p.locator('[data-spam-check]').first().click();await p.waitForFunction(()=>document.querySelector('#admin-notice').textContent.includes('очередь'));
  await p.locator('#admin-spam-all').click();await p.waitForSelector('#admin-action-form');
  assert((await p.locator('#dialog-content').innerText()).includes('@SpamBot'));
  await p.locator('#admin-action-form [type="submit"]').click();await p.waitForFunction(()=>document.querySelector('#admin-notice').textContent.includes('Поставлено в очередь'));
  assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await p.screenshot({path:'/workspace/session-shope-previews/spam-admin-mobile.png',fullPage:true});
  assert.deepEqual(errors,[]);
  console.log('PASS: per-product spam labels/time/source, mobile layout, single and bulk admin queue controls');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
