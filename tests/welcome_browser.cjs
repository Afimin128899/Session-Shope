// Run with integration_welcome.py --serve. Local database only, no real payments.
const {chromium}=require('playwright'),crypto=require('crypto'),assert=require('assert/strict');
function auth(id){const values={auth_date:String(Math.floor(Date.now()/1000)),user:JSON.stringify({id,first_name:'Fixture',username:'fixture'})};const key=crypto.createHmac('sha256','WebAppData').update('123456:local-test-token-not-for-production').digest();values.hash=crypto.createHmac('sha256',key).update(Object.keys(values).sort().map(k=>k+'='+values[k]).join('\n')).digest('hex');return new URLSearchParams(values).toString();}
(async()=>{
 const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox']});const errors=[];
 async function open(id){const context=await browser.newContext({viewport:{width:320,height:844}});await context.route('https://telegram.org/**',r=>r.abort());await context.addInitScript(raw=>{window.Telegram={WebApp:{initData:raw,ready(){},expand(){},setHeaderColor(){},setBackgroundColor(){}}}},auth(id));const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));await page.goto('http://127.0.0.1:8092');await page.waitForFunction(()=>Boolean(window.SBAND_USER));return page;}
 async function profile(page){await page.locator('.mobile-nav [data-tab=profile]').click();await page.waitForSelector('#profile-page:not([hidden])');}
 try{
  const [first,second]=await Promise.all([open(204),open(204)]);
  for(const page of [first,second]){assert.equal(Number(await page.evaluate(()=>window.SBAND_USER.balance)),4);await profile(page);assert(await page.locator('#welcome-bonus').isVisible());assert((await page.locator('#welcome-bonus').innerText()).includes('4 ₽'));assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);}
  await first.screenshot({path:'/workspace/session-shope-previews/welcome-bonus-mobile.png',fullPage:true});
  await second.reload();await second.waitForFunction(()=>Boolean(window.SBAND_USER));assert.equal(Number(await second.evaluate(()=>window.SBAND_USER.balance)),4);
  await first.locator('#profile-page [data-language=en]').click();await first.waitForFunction(()=>document.documentElement.lang==='en');assert((await first.locator('#welcome-bonus').innerText()).includes('welcome bonus'));
  const old=await open(43);await profile(old);assert.equal(Number(await old.evaluate(()=>window.SBAND_USER.balance)),17.5);assert(await old.locator('#welcome-bonus').isHidden());
  assert.deepEqual(errors,[]);console.log('PASS: two simultaneous mobile tabs show one RUB 4 welcome credit, reload preserves the balance, RU/EN receipt renders at 320px, old users see no false bonus; no JavaScript errors');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
