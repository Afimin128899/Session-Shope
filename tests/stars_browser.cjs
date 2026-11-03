// Standalone offline UI regression. All API/payment responses and Telegram SDK are fixtures.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../miniapp/static');
const server = http.createServer((req, res) => {
 const pathname = new URL(req.url, 'http://localhost').pathname;
 const file = pathname === '/' ? 'index.html' : pathname.startsWith('/assets/') ? pathname.slice(8) : '';
 const filename = path.resolve(root, file);
 if (!file || !filename.startsWith(root + path.sep) || !fs.existsSync(filename)) {res.writeHead(404);res.end();return;}
 const ext = path.extname(filename);
 res.setHeader('Content-Type', ({'.html':'text/html','.js':'application/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png'})[ext] || 'application/octet-stream');
 res.end(fs.readFileSync(filename));
});
(async () => {
 await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
 const browser = await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try {
  async function fixture(native = true) {
   const context = await browser.newContext({viewport:{width:390,height:844}});
   await context.route('https://telegram.org/**', route => route.abort());
   await context.addInitScript(native => {
    window.STAR_CALLS = [];
    window.Telegram = {WebApp:{initData:'fixture-only',ready(){},expand(){},setHeaderColor(){},setBackgroundColor(){}}};
    if (native) window.Telegram.WebApp.openInvoice = (url, callback) => {window.STAR_CALLS.push(url);window.INVOICE_CALLBACK = callback;};
   }, native);
   const state = {status:'pending',body:[],balance:'10.00',sequence:0};
   await context.route('**/api/**', async route => {
    const request = route.request(), url = new URL(request.url());
    let data;
    if (url.pathname === '/api/me') data = {user:{id:42,first_name:'Fixture',username:'fixture'},balance:state.balance,balance_usdt:'0',version:'fixture',bot_username:'fixture_bot',is_admin:false};
    else if (url.pathname === '/api/shop-info') data = {wholesale:{minimum:'500',percent:'15'},support_hours:'Fixture',response_time:'Fixture'};
    else if (url.pathname === '/api/catalog') data = {categories:[],items:[],has_more:false};
    else if (url.pathname === '/api/payment-methods') data = {items:[{id:'crypto',name:'Crypto Pay',enabled:true},{id:'stars',name:'Telegram Stars ⭐',enabled:true,unit:'XTR',rate:'1.20',min:1,max:10000}]};
    else if (url.pathname === '/api/invoices' && request.method() === 'POST') {
     const body=request.postDataJSON();state.body.push(body);state.sequence++;
     data = body.provider === 'stars' ? {provider:'stars',invoice_id:'fixture-stars-'+state.sequence,pay_url:'https://t.me/$fixture'+state.sequence,stars:body.stars,amount:(body.stars*120/100).toFixed(2),rate:'1.20',currency:'XTR'} : {provider:body.provider,invoice_id:'fixture-crypto',pay_url:'https://t.me/fixture_external_invoice',amount:body.amount};
    } else if (url.pathname.startsWith('/api/invoices/')) data = {status:state.status};
    else throw new Error('Unexpected fixture request: '+request.method()+' '+url.pathname);
    await route.fulfill({status:200,json:data});
   });
   const page=await context.newPage(),errors=[];
   page.on('pageerror', e => errors.push(e.message));
   await page.goto('http://127.0.0.1:'+server.address().port);
   await page.waitForFunction(() => document.querySelector('#header-balance').textContent.includes('10'));
   await page.locator('[data-topup]').first().click();await page.waitForSelector('#topup-method');
   await page.locator('#topup-method').selectOption('stars');
   return {context,page,state,errors};
  }
  const first=await fixture(),p=first.page;
  assert((await p.locator('#topup-amount-label').textContent()).includes('звёзд'));
  assert.equal(await p.locator('#topup-amount').getAttribute('step'),'1');
  assert.equal(await p.locator('#topup-amount').inputValue(),'100');
  assert((await p.locator('#topup-quote').textContent()).includes('120,00 ₽'));
  await p.locator('#topup-amount').fill('1');
  assert((await p.locator('#topup-quote').textContent()).includes('1,20 ₽'));
  for (const invalid of ['1.5','0','10001']) {
   await p.locator('#topup-amount').fill(invalid);
   assert.equal(await p.locator('#create-invoice').isDisabled(),true);
  }
  assert.equal(first.state.body.length,0);
  await p.locator('#topup-amount').fill('100');await p.locator('#create-invoice').click();await p.waitForSelector('#pay-stars');
  assert.deepEqual(first.state.body,[{provider:'stars',stars:100}]);
  assert((await p.locator('#dialog-content').textContent()).includes('1 ⭐ = 1,20 ₽'));
  await p.locator('#pay-stars').click();
  assert.deepEqual(await p.evaluate(()=>window.STAR_CALLS),['https://t.me/$fixture1']);
  assert.equal(await p.locator('#pay-stars').isDisabled(),true);
  await p.evaluate(()=>window.INVOICE_CALLBACK('cancelled'));
  assert.equal(await p.locator('#pay-stars').isEnabled(),true);
  await p.locator('#pay-stars').click();
  await p.evaluate(()=>window.INVOICE_CALLBACK('paid'));
  await p.waitForFunction(()=>document.querySelector('#invoice-state').textContent.includes('Проверяем'));
  assert((await p.locator('#header-balance').textContent()).includes('10'));
  assert(!(await p.locator('#invoice-state').textContent()).includes('Баланс пополнен'));
  first.state.status='credited';first.state.balance='130.00';
  await p.locator('#verify-invoice').click();await p.waitForFunction(()=>document.querySelector('#invoice-state').textContent.includes('Баланс пополнен'));
  assert((await p.locator('#header-balance').textContent()).includes('130'));
  assert.equal(await p.locator('#pay-stars').isDisabled(),true);
  await p.locator('#another-invoice').click();await p.waitForSelector('#topup-method');
  await p.locator('#topup-amount').fill('50.25');await p.locator('#create-invoice').click();await p.waitForSelector('.payment-link');
  assert.deepEqual(first.state.body.at(-1),{provider:'crypto',amount:'50.25'});
  assert.equal(await p.locator('.payment-link').getAttribute('href'),'https://t.me/fixture_external_invoice');
  assert.deepEqual(first.errors,[]);
  const fallback=await fixture(false),f=fallback.page;
  await f.locator('#create-invoice').click();await f.waitForSelector('.payment-link');
  assert.equal(await f.locator('#pay-stars').count(),0);
  assert.equal(await f.locator('.payment-link').getAttribute('href'),'https://t.me/$fixture1');
  assert((await f.locator('.payment-link').textContent()).includes('100 ⭐'));
  assert.equal(await f.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  assert.deepEqual(fallback.errors,[]);
  console.log('PASS: exact Stars quote and integer bounds, native payment, no optimistic credit, server-only settlement, external RUB invoices and Telegram-link fallback');
 } finally {await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(e=>{console.error(e);process.exit(1)});
