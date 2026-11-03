// Start: python tests/demo_fixture.py. Only fixture Telegram credentials are used.
const {chromium}=require('playwright'),crypto=require('node:crypto'),assert=require('node:assert/strict'),fs=require('node:fs');
const values={auth_date:String(Math.floor(Date.now()/1000)),user:JSON.stringify({id:42,first_name:'Demo Admin'})};
const secret=crypto.createHmac('sha256','WebAppData').update('123456:local-test-token-not-for-production').digest();
values.hash=crypto.createHmac('sha256',secret).update(Object.keys(values).sort().map(k=>k+'='+values[k]).join('\n')).digest('hex');
(async()=>{
 const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  const context=await browser.newContext({viewport:{width:390,height:844}});
  await context.route('https://telegram.org/**',r=>r.abort());
  await context.addInitScript(raw=>{window.Telegram={WebApp:{initData:raw,ready(){},expand(){}}};},new URLSearchParams(values).toString());
  const p=await context.newPage(),errors=[],requests=[];p.on('pageerror',e=>errors.push(e.message));p.on('request',r=>{if(r.url().includes('/api/'))requests.push(new URL(r.url()).pathname);});
  await p.goto('http://127.0.0.1:8087/demo');await p.waitForSelector('[data-add]');
  assert((await p.locator('.training-header').innerText()).includes('ТЕСТОВЫЙ РЕЖИМ'));
  await p.locator('[data-add="1"]').click();await p.waitForFunction(()=>document.querySelector('#cart-summary').textContent.includes('аккаунт 1'));
  await p.locator('#promo').fill('DEMO10');assert((await p.locator('#total').innerText()).includes('90'));
  await p.locator('#checkout').click();await p.waitForSelector('[data-code]');assert((await p.locator('#balance').innerText()).includes('910'));
  await p.locator('[data-code]').click();await p.waitForFunction(()=>document.querySelector('#notice').textContent.includes('TEST-000001'));
  await p.locator('[data-refund]').click();await p.waitForFunction(()=>document.querySelector('#orders').textContent.includes('возврат выполнен'));
  await p.locator('#provider').selectOption('stars');await p.locator('#payment [type=submit]').click();await p.waitForSelector('[data-pay]');
  assert((await p.locator('#invoices').innerText()).includes('120'));
  await p.locator('[data-pay]').click();await p.waitForFunction(()=>document.querySelector('#balance').textContent.includes('120'));
  await p.locator('#reward').click();await p.waitForFunction(()=>document.querySelector('#notice').textContent.includes('Учебный бонус'));
  p.once('dialog',dialog=>dialog.accept());await p.locator('#reset').click();await p.waitForFunction(()=>document.querySelector('#notice').textContent==='Учебный сценарий готов.');
  assert((await p.locator('#balance').innerText()).includes('000'));
  assert(requests.every(path=>path.startsWith('/api/demo/')));
  assert.deepEqual(errors,[]);assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  fs.mkdirSync('/workspace/session-shope-previews',{recursive:true});await p.screenshot({path:'/workspace/session-shope-previews/test-mode-mobile.png',fullPage:true});
  console.log('PASS: real demo API, discounted purchase, code, refund, fake Stars, reward, reset and no production API calls');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
