// Isolated UI contract fixtures: no production credentials, database or payments.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const root=path.join(__dirname,'../miniapp/static');
(async()=>{
 const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 const errors=[];fs.mkdirSync('/workspace/session-shope-previews',{recursive:true});
 try{for(const width of [320,390,768,1440]){
  const ctx=await browser.newContext({viewport:{width,height:900}});let language='ru',catalogueDelay=0,catalogueRequests=0,invoiceRequests=0;const departments=['email','gmail','chatgpt','roblox','discord','steam','spotify','youtube'].map(slug=>({slug:'section-'+slug,name:slug==='email'?'Почта':slug==='chatgpt'?'ChatGPT':slug==='gmail'?'Gmail':slug[0].toUpperCase()+slug.slice(1),emoji:'◇',is_active:0}));const supportMessages=[];
  const items=[['auto-cl-clear','Чили 🇨🇱 · Без спамблока',120],['auto-us-permanent','США 🇺🇸 · Вечный спамблок',90],['fr','Франция 🇫🇷',250],['unknown','Другая страна',80]].map(([category,name,price],i)=>({id:i+1,category,name,price,original_price:price+20,discount:10,available:true,product_id:'#0'+(i+1),telegram_user_id:123456789+i,phone:'+56 ••• •• 2345',characteristics:{is_premium:i===2,warranty_hours:24,two_fa:'Да',spam_check:{status:i===1?'permanent':'clear',label:i===1?'Вечный спамблок':'Нет спамблока',checked_at:'2026-11-08T10:00:00Z'}}}));
  const categories=[{slug:'de',name:'Германия 🇩🇪',count:0},...items.map(i=>({slug:i.category,name:i.name,count:1,min_price:i.price})),...['es','gb','tr','kz','id','br','in','jp','ca','pl'].map(slug=>({slug,name:slug.toUpperCase(),count:0}))];
  await ctx.addInitScript(()=>{window.Telegram={WebApp:{initData:'ui-fixture',ready(){},expand(){},setHeaderColor(){},setBackgroundColor(){},openTelegramLink(url){window.sharedURL=url;}}};Object.defineProperty(navigator,'clipboard',{value:{async writeText(value){window.savedCopy=value;}},configurable:true});});
  await ctx.route('**/*',async route=>{
   const u=new URL(route.request().url()),p=u.pathname;
   if(u.hostname!=='sband.test')return route.abort();
   if(p.startsWith('/api/')){
    let data={};const key=p.slice(5),body=route.request().postDataJSON();
    if(key==='app-info')data={bot_username:'fixture_bot'};
    else if(key==='payment-methods')data={items:[{id:'crypto',name:'Crypto Pay',enabled:true,min:'10',max:'1000000'},{id:'xrocket',name:'xRocket',enabled:true,min:'10',max:'1000000'},{id:'lave',name:'Laveshka (Lava Pay)',enabled:true,min:'10',max:'1000000'},{id:'platega',name:'СБП · Рубли',enabled:true,min:'1',max:'10000'},{id:'stars',name:'Telegram Stars',enabled:true,min:'1',max:'10000'}]};
    else if(key==='invoices'){invoiceRequests++;assert.equal(body.provider,'platega');assert.equal(body.amount,'1');return route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({error:'Оплата пока недоступна',code:'payment_unavailable'})});}
    else if(key==='payment-history')data={items:u.searchParams.has('before')?[{id:1,method:'crypto_pay',amount:'10',currency:'RUB',created_at:'2026-11-01 10:00:00'}]:[{id:2,method:'stars_pay',amount:'120',currency:'RUB',created_at:1794132000}],has_more:!u.searchParams.has('before')};
    else if(key==='departments')data={items:departments};
    else if(key==='support'&&route.request().method()==='POST'){supportMessages.unshift({id:supportMessages.length+1,author_role:'user',body:body.body});data={ticket_id:77};}
    else if(key==='support')data={items:supportMessages.length?[{id:77,purchase_id:null,status:'open'}]:[]};
    else if(key==='support/77')data={ticket:{id:77,purchase_id:null},messages:supportMessages,has_more:false};
    else if(key==='support/77/reply'){supportMessages.unshift({id:supportMessages.length+1,author_role:'user',body:body.body});data={ok:true};}
    else if(key==='preferences/language'){language=body.language;data={language};}
    else if(key==='me')data={language,user:{id:42,first_name:'Alex',username:'alex'},balance:1250,balance_usdt:0,welcome_bonus:4,version:'5.11.0',is_admin:true,bot_username:'fixture_bot',shop_status:{}};
    else if(key==='shop-info')data={wholesale:{minimum:500,percent:15}};
    else if(key==='cart'&&route.request().method()==='POST'){Object.assign(items.find(i=>i.id===body.account_id),{in_cart:true,reserved_until:new Date(Date.now()+300000).toISOString()});}
    else if(key==='favorites'&&route.request().method()==='POST'){items.find(i=>i.id===body.account_id).favorite=body.enabled;}
    else if(['catalog','favorites','cart'].includes(key)){if(key==='catalog'){catalogueRequests++;if(catalogueDelay)await new Promise(resolve=>setTimeout(resolve,catalogueDelay));}data={items:items.filter(i=>key==='cart'?i.in_cart:key==='favorites'?i.favorite:true),categories,has_more:false};}
    else if(key.startsWith('products/'))data=items.find(i=>i.id===Number(key.split('/')[1]));
    else if(key==='admin/categories')data={items:categories};
    else if(key==='admin/overview')data={stock:4,orders:12,tickets:2,users:64,approvals:0,sales:[]};
    else if(key==='orders')data={items:[],has_more:false};
    return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
   }
   const file=p==='/'?path.join(root,'index.html'):path.join(root,p.replace('/assets/',''));
   if(!file.startsWith(root)||!fs.existsSync(file))return route.fulfill({status:404,body:'not found'});
   const types={'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.svg':'image/svg+xml','.png':'image/png','.webp':'image/webp'};
   await route.fulfill({contentType:types[path.extname(file)],body:fs.readFileSync(file)});
  });
  const p=await ctx.newPage();p.on('pageerror',e=>errors.push(e.message));await p.goto('https://sband.test/');await p.waitForSelector('.account-card');
  const nav=width<=700?'.mobile-nav':'.side-nav';
  assert.equal(await p.locator('[data-tab="messages"]').count(),0);
  assert.equal(await p.locator('.mobile-nav button').count(),2);
  await p.locator(`${nav} [data-tab="catalog"]`).click();await p.waitForSelector('.account-card');
  if(width===390){
    const refresh=p.locator('#refresh');await refresh.scrollIntoViewIfNeeded();const box=await refresh.boundingBox(),prior=catalogueRequests;
    catalogueDelay=500;
    await p.mouse.move(box.x+box.width/2,box.y+box.height/2);await p.mouse.down();
    await p.waitForFunction(()=>new DOMMatrix(getComputedStyle(document.querySelector('#refresh')).transform).a<.99);
    await p.mouse.up();await p.waitForSelector('#refresh.is-loading[aria-busy="true"]');
    assert(await refresh.isDisabled());await refresh.evaluate(button=>button.click());
    assert.equal(await refresh.getAttribute('aria-label'),'Обновить');
    const during=await refresh.evaluate(b=>b.offsetWidth);assert(Math.abs(during-box.width)<.2);
    await p.waitForSelector('#refresh:not(:disabled):not(.is-loading)');assert.equal(catalogueRequests,prior+1);assert.equal(await refresh.getAttribute('aria-busy'),null);
    await p.emulateMedia({reducedMotion:'reduce'});await refresh.focus();await p.keyboard.down('Space');
    assert.equal(await refresh.evaluate(b=>getComputedStyle(b).transform),'none');await p.keyboard.up('Space');await p.waitForSelector('#refresh.is-loading');
    assert.equal(await refresh.evaluate(b=>getComputedStyle(b,'::after').animationName),'none');
    await p.waitForSelector('#refresh:not(:disabled):not(.is-loading)');catalogueDelay=0;await p.emulateMedia({reducedMotion:'no-preference'});
  }
  assert.equal(await p.locator('.account-card .country-image').count(),4);
  assert.equal(await p.locator('#country-feature').isVisible(),false);
  assert.equal(await p.locator('#categories').isVisible(),false);
  assert.equal(await p.locator('.departments-section').isVisible(),false);
  assert(await p.locator('#search').isVisible());
  await p.locator('[data-sort="price_asc"]').click();
  assert.equal(await p.locator('#sort').inputValue(),'price_asc');
  assert.equal(await p.locator('[data-sort="price_asc"]').getAttribute('aria-pressed'),'true');
  await p.locator('#open-filters').click();assert(await p.locator('#premium-filter').isVisible());await p.locator('#sort').selectOption('discount');await p.waitForFunction(()=>![...document.querySelectorAll('[data-sort]')].some(b=>b.getAttribute('aria-pressed')==='true'));
  await p.locator('#open-filters').click();assert.equal(await p.locator('#premium-filter').isVisible(),false);await p.locator('[data-sort="new"]').click();
  await p.locator('.country-image').evaluateAll(images=>images.forEach(i=>i.loading='eager'));
  await p.waitForFunction(()=>[...document.querySelectorAll('.country-image')].every(i=>i.complete&&i.naturalWidth>0));
  assert((await p.locator('.account-card .country-image').first().getAttribute('src')).endsWith('/cl.svg'));
  assert((await p.locator('.account-card .country-image').last().getAttribute('src')).endsWith('/unknown.svg'));
  assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`catalog overflow ${width}`);
  await p.screenshot({path:`/workspace/session-shope-previews/redesign-${width}-ru.png`,fullPage:true});
  await p.locator('#catalog-grid [data-features="1"]').click();await p.waitForSelector('#dialog-title');assert(await p.locator('.product-cover .country-image').isVisible());await p.locator('#close-dialog').click();
  await p.locator('[data-favorite="1"]').click();await p.waitForFunction(()=>document.querySelector('[data-favorite="1"]').getAttribute('aria-pressed')==='true');
  await p.locator('[data-add="1"]').click();await p.waitForFunction(()=>document.querySelector('[data-add="1"]').textContent.includes('В корзине'));
  await p.locator(`${nav} [data-tab="profile"]`).click();await p.locator('#profile-page [data-tab="cart"]').click();await p.waitForSelector('#cart-summary:not([hidden])');assert((await p.locator('#cart-total').innerText()).includes('120'));
  await p.locator(`${nav} [data-tab="profile"]`).click();
  await p.locator('#copy-profile-id').click();assert.equal(await p.evaluate(()=>window.savedCopy),'42');
  await p.locator('#toast').evaluate(e=>e.hidden=true);
  await p.screenshot({path:`/workspace/session-shope-previews/minimal-profile-${width}-ru.png`,fullPage:true});
  await p.locator('[data-payment-history]').click();await p.waitForSelector('#history-rows');
  assert((await p.locator('#history-rows').innerText()).includes('Telegram Stars'));
  await p.locator('#history-more').click();await p.waitForFunction(()=>document.querySelectorAll('.history-row').length===2);
  assert.equal(await p.locator('#history-more').isVisible(),false);await p.locator('#close-dialog').click();
  await p.locator('#profile-page [data-topup]').click();await p.waitForSelector('#topup-amount');
  assert.equal(await p.locator('[data-payment-choice]').count(),5);
  await p.locator('[data-topup-preset="300"]').click();assert.equal(await p.locator('#topup-amount').inputValue(),'300');
  await p.locator('[data-payment-choice="crypto"]').focus();await p.keyboard.press('ArrowRight');assert.equal(await p.locator('#topup-method').inputValue(),'xrocket');
  await p.locator('[data-payment-choice="stars"]').click();await p.locator('#topup-amount').fill('1');
  assert((await p.locator('#topup-quote').innerText()).includes('1,20'));
  assert((await p.locator('#topup-total').innerText()).includes('1,2'));
  await p.locator('#topup-amount').fill('1.5');assert(await p.locator('#create-invoice').isDisabled());
  await p.locator('[data-payment-choice="platega"]').click();assert.equal(await p.locator('#topup-amount').inputValue(),'300');
  await p.locator('#topup-amount').fill('10000.01');assert(await p.locator('#create-invoice').isDisabled());
  await p.locator('#topup-amount').fill('1');assert.equal(await p.locator('#create-invoice').isDisabled(),false);
  await p.locator('#create-invoice').click();await p.waitForSelector('#dialog-error:not([hidden])');
  assert.equal(invoiceRequests,1);assert((await p.locator('#dialog-error').innerText()).includes('недоступна'));
  await p.locator('[data-payment-choice="crypto"]').click();await p.locator('[data-topup-preset="300"]').click();
  assert.equal(await p.locator('#dialog-error').isVisible(),false);assert(await p.locator('#create-invoice').isVisible());
  await p.screenshot({path:`/workspace/session-shope-previews/minimal-topup-${width}-ru.png`,fullPage:true});
  assert.equal(await p.evaluate(()=>document.querySelector('#purchase-dialog').scrollWidth>document.querySelector('#purchase-dialog').clientWidth),false,`topup overflow ${width}`);
  await p.locator('#close-dialog').click();
  await p.locator(`${nav} [data-tab="profile"]`).click();await p.locator('#profile-page [data-language="en"]').click();await p.waitForFunction(()=>document.documentElement.lang==='en');
  await p.locator('#profile-page [data-share-app]').click();await p.waitForSelector('#app-share-link');
  assert.equal(await p.locator('#app-share-link').inputValue(),'https://t.me/fixture_bot?start=miniapp');
  await p.locator('#copy-app-link').click();await p.waitForFunction(()=>window.savedCopy==='https://t.me/fixture_bot?start=miniapp');
  await p.locator('#send-app-link').click();const shared=new URL(await p.evaluate(()=>window.sharedURL));assert.equal(shared.hostname,'t.me');assert.equal(shared.searchParams.get('url'),'https://t.me/fixture_bot?start=miniapp');assert(!shared.href.includes('ui-fixture'));
  await p.locator('#close-dialog').click();
  assert((await p.locator('#profile-page h1').innerText()).includes('profile'));assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`profile overflow ${width}`);
  await p.screenshot({path:`/workspace/session-shope-previews/minimal-profile-${width}-en.png`,fullPage:true});await p.locator('[data-header-search]').click();await p.waitForSelector('#market-page:not([hidden])');await p.waitForFunction(()=>document.activeElement===document.querySelector('#search'));
  await p.locator(`${nav} [data-tab="catalog"]`).click();await p.waitForSelector('.account-card');assert((await p.locator('[data-add="2"]').innerText()).includes('Add to cart'));assert((await p.locator('.account-card h3').first().innerText()).includes('Chile'));assert((await p.locator('[data-spam-status="2"]').innerText()).includes('Permanent spam restriction'));await p.locator('#toast').evaluate(e=>e.hidden=true);
  await p.screenshot({path:`/workspace/session-shope-previews/redesign-${width}-en.png`,fullPage:true});
  await p.locator(`${nav} [data-tab="profile"]`).click();await p.locator('#profile-page [data-open-admin]').click();await p.waitForSelector('.stat-card');assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`admin overflow ${width}`);
  await p.screenshot({path:`/workspace/session-shope-previews/redesign-admin-${width}.png`,fullPage:true});await p.evaluate(()=>document.dispatchEvent(new Event('sband-auth-error')));await p.waitForSelector('#public-open-bot:not([hidden])');assert.equal(await p.locator('#public-open-bot').getAttribute('href'),'https://t.me/fixture_bot?start=miniapp');await ctx.close();
 }
 assert.deepEqual(errors,[]);console.log('PASS: RU/EN at 320,390,768,1440px; compact market and no category blocks/messages; flags, filters, product, favorite, cart; profile/ID/history, provider choices, Stars rate and SBP limit/stub, safe sharing/language and admin; no overflow or JS errors.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
