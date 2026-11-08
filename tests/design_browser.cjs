// Isolated UI contract fixtures: no production credentials, database or payments.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const root=path.join(__dirname,'../miniapp/static');
(async()=>{
 const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 const errors=[];fs.mkdirSync('/workspace/session-shope-previews',{recursive:true});
 try{for(const width of [320,390,768,1440]){
  const ctx=await browser.newContext({viewport:{width,height:900}});let language='ru';
  const items=[['auto-cl-clear','Чили 🇨🇱 · Без спамблока',120],['auto-us-permanent','США 🇺🇸 · Вечный спамблок',90],['fr','Франция 🇫🇷',250],['unknown','Другая страна',80]].map(([category,name,price],i)=>({id:i+1,category,name,price,original_price:price+20,discount:10,available:true,product_id:'#0'+(i+1),telegram_user_id:123456789+i,phone:'+56 ••• •• 2345',characteristics:{is_premium:i===2,warranty_hours:24,two_fa:'Да',spam_check:{status:i===1?'permanent':'clear',label:i===1?'Вечный спамблок':'Нет спамблока',checked_at:'2026-11-08T10:00:00Z'}}}));
  const categories=[{slug:'de',name:'Германия 🇩🇪',count:0},...items.map(i=>({slug:i.category,name:i.name,count:1})),...['es','gb','tr','kz','id','br','in','jp','ca','pl'].map(slug=>({slug,name:slug.toUpperCase(),count:0}))];
  await ctx.addInitScript(()=>{window.Telegram={WebApp:{initData:'ui-fixture',ready(){},expand(){},setHeaderColor(){},setBackgroundColor(){}}};});
  await ctx.route('**/*',async route=>{
   const u=new URL(route.request().url()),p=u.pathname;
   if(u.hostname!=='sband.test')return route.abort();
   if(p.startsWith('/api/')){
    let data={};const key=p.slice(5),body=route.request().postDataJSON();
    if(key==='preferences/language'){language=body.language;data={language};}
    else if(key==='me')data={language,user:{id:42,first_name:'Alex',username:'alex'},balance:1250,balance_usdt:0,welcome_bonus:4,version:'5.11.0',is_admin:true,bot_username:'fixture_bot',shop_status:{}};
    else if(key==='shop-info')data={wholesale:{minimum:500,percent:15}};
    else if(key==='cart'&&route.request().method()==='POST'){Object.assign(items.find(i=>i.id===body.account_id),{in_cart:true,reserved_until:new Date(Date.now()+300000).toISOString()});}
    else if(key==='favorites'&&route.request().method()==='POST'){items.find(i=>i.id===body.account_id).favorite=body.enabled;}
    else if(['catalog','favorites','cart'].includes(key)){data={items:items.filter(i=>key==='cart'?i.in_cart:key==='favorites'?i.favorite:true),categories,has_more:false};}
    else if(key.startsWith('products/'))data=items.find(i=>i.id===Number(key.split('/')[1]));
    else if(key==='admin/categories')data={items:categories};
    else if(key==='admin/overview')data={stock:4,orders:12,tickets:2,users:64,approvals:0,sales:[]};
    else if(key==='orders')data={items:[],has_more:false};
    return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
   }
   const file=p==='/'?path.join(root,'index.html'):path.join(root,p.replace('/assets/',''));
   if(!file.startsWith(root)||!fs.existsSync(file))return route.fulfill({status:404,body:'not found'});
   const types={'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.svg':'image/svg+xml','.png':'image/png'};
   await route.fulfill({contentType:types[path.extname(file)],body:fs.readFileSync(file)});
  });
  const p=await ctx.newPage();p.on('pageerror',e=>errors.push(e.message));await p.goto('https://sband.test/');await p.waitForSelector('.account-card');
  assert.equal(await p.locator('.account-card .country-image').count(),4);
  assert.equal(await p.locator('.category').nth(1).getAttribute('data-category'),'auto-cl-clear');
  await p.locator('#countries-toggle').click();assert.equal(await p.locator('#countries-toggle').getAttribute('aria-expanded'),'true');
  await p.locator('#countries-toggle').click();await p.locator('.filter-panel summary').click();assert(await p.locator('#search').isVisible());await p.locator('.filter-panel summary').click();
  await p.locator('.country-image').evaluateAll(images=>images.forEach(i=>i.loading='eager'));
  await p.waitForFunction(()=>[...document.querySelectorAll('.country-image')].every(i=>i.complete&&i.naturalWidth>0));
  assert((await p.locator('.country-image').first().getAttribute('src')).endsWith('/cl.svg'));
  assert((await p.locator('.account-card .country-image').last().getAttribute('src')).endsWith('/unknown.svg'));
  assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`catalog overflow ${width}`);
  await p.screenshot({path:`/workspace/session-shope-previews/redesign-${width}-ru.png`,fullPage:true});
  await p.locator('[data-features="1"]').click();await p.waitForSelector('#dialog-title');assert(await p.locator('.product-cover .country-image').isVisible());await p.locator('#close-dialog').click();
  await p.locator('[data-favorite="1"]').click();await p.waitForFunction(()=>document.querySelector('[data-favorite="1"]').getAttribute('aria-pressed')==='true');
  await p.locator('[data-add="1"]').click();await p.waitForFunction(()=>document.querySelector('[data-add="1"]').textContent.includes('В корзине'));
  const nav=width<=700?'.mobile-nav':'.side-nav';await p.locator(`${nav} [data-tab="cart"]`).click();await p.waitForSelector('#cart-summary:not([hidden])');assert((await p.locator('#cart-total').innerText()).includes('120'));
  await p.locator(`${nav} [data-tab="profile"]`).click();await p.locator('#profile-page [data-language="en"]').click();await p.waitForFunction(()=>document.documentElement.lang==='en');
  assert((await p.locator('#profile-page h1').innerText()).includes('profile'));assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`profile overflow ${width}`);
  await p.locator(`${nav} [data-tab="catalog"]`).click();await p.waitForSelector('.account-card');assert((await p.locator('[data-add="2"]').innerText()).includes('Add to cart'));assert((await p.locator('#countries-toggle').innerText()).includes('All countries'));assert((await p.locator('.account-card h3').first().innerText()).includes('Chile'));assert((await p.locator('[data-spam-status="2"]').innerText()).includes('Permanent spam restriction'));await p.locator('#toast').evaluate(e=>e.hidden=true);
  await p.screenshot({path:`/workspace/session-shope-previews/redesign-${width}-en.png`,fullPage:true});
  await p.locator(`${nav} [data-tab="profile"]`).click();await p.locator('#profile-page [data-open-admin]').click();await p.waitForSelector('.stat-card');assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`admin overflow ${width}`);
  await p.screenshot({path:`/workspace/session-shope-previews/redesign-admin-${width}.png`,fullPage:true});await ctx.close();
 }
 assert.deepEqual(errors,[]);console.log('PASS: RU/EN at 320,390,768,1440px; country images and safe fallback; product dialog, favorite, cart reservation/total, profile/language and admin; no overflow or JS errors.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
