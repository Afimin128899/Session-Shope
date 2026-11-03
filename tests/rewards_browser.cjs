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
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  const context=await browser.newContext({viewport:{width:390,height:844}});
  await context.route('https://telegram.org/**',r=>r.abort());
  await context.addInitScript(()=>{window.Telegram={WebApp:{initData:'fixture',ready(){},expand(){},setHeaderColor(){},setBackgroundColor(){}}};});
  let balance='100',claims=0;
  await context.route('**/api/**',async route=>{
   const url=new URL(route.request().url());let data;
   if(url.pathname==='/api/me')data={user:{id:42,first_name:'Fixture'},balance,balance_usdt:'0',version:'fixture',bot_username:'fixture_bot'};
   else if(url.pathname==='/api/shop-info')data={wholesale:{minimum:'500',percent:'15'}};
   else if(url.pathname==='/api/catalog')data={categories:[],items:[],has_more:false};
   else if(url.pathname==='/api/rewards')data={eligible:true,paid:'50',minimum:'50',next_at:null};
   else if(url.pathname==='/api/rewards/claim'){claims++;balance='104';data={amount:'4',balance};}
   else throw Error('Unexpected path '+url.pathname);
   await route.fulfill({status:200,json:data});
  });
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:'+server.address().port);await page.waitForSelector('#login-panel',{state:'hidden'});
  await page.locator('.mobile-nav [data-tab="profile"]').click();await page.locator('[data-wheel]').click();await page.waitForSelector('#claim-wheel');
  assert((await page.locator('#dialog-content').innerText()).includes('72 часа'));
  await page.locator('#claim-wheel').click();await page.waitForFunction(()=>document.querySelector('#dialog-title')?.textContent.includes('4 ₽'));
  await page.waitForFunction(()=>document.querySelector('#profile-balance').textContent.includes('104'));
  assert.equal(claims,1);assert.deepEqual(errors,[]);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  console.log('PASS: profile bonus entry, transparent72h rules, server reward and synchronized wallet, mobile layout');
 }finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(e=>{console.error(e);process.exit(1)});
