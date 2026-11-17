/* Isolated browser fixtures: no real account, wallet, payment, or admin mutations. */
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=path.join(__dirname,'../miniapp'),artifacts='/workspace/session-shope-previews';
(async()=>{
 fs.mkdirSync(artifacts,{recursive:true});
 const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 let previews=0,buys=0;const errors=[];
 try{
 for(const width of [320,360,390,768,1440]){
  const context=await browser.newContext({viewport:{width,height:1000},acceptDownloads:true});
  await context.addInitScript(()=>{window.Telegram={WebApp:{initData:'fixture',ready(){},expand(){},setHeaderColor(){},setBackgroundColor(){},openTelegramLink(){}}};});
  await context.route('**/*',async route=>{
   const url=new URL(route.request().url()),p=url.pathname;
   if(!url.hostname.endsWith('tg-market.test'))return route.abort();
   let data={};
   if(p.startsWith('/api/')){
    if(p==='/api/me')data={user:{id:42,username:'market_admin',first_name:'Александр'},balance:'3250.00',cash_balance:'3000',bonus_balance:'250',is_admin:true,bot_username:'fixture_bot'};
    else if(p==='/api/configurator/preview'){previews++;data={count:148,unit_price:'90.00',warranty_hours:[24],wholesale:{minimum:'500',percent:'15'},quantities:Array.from({length:20},(_,i)=>({quantity:i+1,total:((i+1)*90*((i+1)*90>=500?.85:1)).toFixed(2),rate:(i+1)*90>=500?'15':'0'}))};}
    else if(p==='/api/configurator/quote')data={token:'owned-token',quantity:10,total:'765.00',rate:'15',warranty_hours:[24],expires_at:Date.now()/1000+300};
    else if(p==='/api/configurator/buy'){buys++;data={order_ids:[10482],paid_amount:'765.00',balance:'2485.00'};}
    else if(p==='/api/category-market')data={items:[{country:'us',name:'США',count:148,min_price:'90'},{country:'gb',name:'Великобритания',count:42,min_price:'120'},{country:'de',name:'Германия',count:80,min_price:'110'},{country:'kz',name:'Казахстан',count:16,min_price:'75'}]};
    else if(p==='/api/admin/identity')data={user:{id:42,username:'market_admin'},is_admin:true};
    else if(p==='/api/admin/overview')data={stock:386,orders:10482,users:1240,approvals:2,tickets:3,sales:[{currency:'RUB',amount:'24850.00'}]};
    else if(p==='/api/admin/settings')data={wholesale_min_total:'500',wholesale_pct:'15',maintenance_mode:'0',sales_paused:'0'};
    else if(p==='/api/admin/users')data={user:{id:42,username:'market_admin',balance:'3250'}};
    else if(p==='/api/payment-methods')data={items:[{id:'heleket',name:'USDT / TON',enabled:true,min:1,max:10000},{id:'platega',name:'СБП',enabled:true,min:1,max:10000}]};
    else if(p==='/api/app-info')data={bot_username:'fixture_bot'};
    else if(/^\/api\/orders\/\d+\/archive$/.test(p))return route.fulfill({status:200,contentType:'application/zip',body:Buffer.from('PK\x03\x04fixture')});
    else if(/^\/api\/orders\/\d+$/.test(p))data={id:10482,status:'issued',status_label:'Оплачен и выдан',number:'+15551110000',password:'fixture-2fa',date:'2026-11-17 12:00:00'};
    else if(p==='/api/health')data={ok:true};
    else data={items:[],has_more:false};
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
   }
   let file=p==='/admin-app'?path.join(base,'admin_static/index.html'):p.startsWith('/admin-assets/')?path.join(base,'admin_static',p.slice(14)):p.startsWith('/store-assets/')?path.join(base,'storefront_v2',p.slice(14)):p.startsWith('/assets/')?path.join(base,'static',p.slice(8)):path.join(base,'storefront_v2/index.html');
   if(!fs.existsSync(file))return route.fulfill({status:404,body:'not found'});
   const type=file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.svg')?'image/svg+xml':file.endsWith('.png')?'image/png':'text/html';
   return route.fulfill({status:200,contentType:type,body:fs.readFileSync(file)});
  });
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));await page.goto('https://tg-market.test/');
  await page.waitForFunction(()=>document.querySelector('#config-stock').textContent.includes('148'));
  assert.equal(await page.locator('body').evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(14, 22, 33)');
  assert.equal(await page.locator('#config-checkout').evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(42, 171, 238)');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'store horizontal overflow at '+width);
  await page.screenshot({path:path.join(artifacts,'tg-market-store-'+width+'.png'),fullPage:true});
  await page.locator('[data-geo=de]').click();await page.waitForFunction(()=>document.querySelector('#config-country').textContent.includes('Германия'));
  await page.locator('[data-age="180"]').click();await page.locator('#config-premium').check();await page.locator('#config-twofa').check();
  await page.waitForFunction(()=>!document.querySelector('#config-checkout').disabled&&document.querySelector('#config-stock').textContent.includes('148'));
  await page.locator('[data-quantity="10"]').click();assert.match(await page.locator('#config-total').textContent(),/765/);
  await page.locator('#config-quantity').fill('0');assert.equal(await page.locator('#config-checkout').isDisabled(),true);
  await page.locator('[data-quantity="10"]').click();await page.locator('#config-checkout').click();await page.locator('#modal').waitFor({state:'visible'});
  assert.match(await page.locator('#modal-content').textContent(),/765/);
  await page.locator('#modal-content button.primary').click();await page.getByText('Аккаунты готовы к выдаче',{exact:true}).waitFor();
  const downloadEvent=page.waitForEvent('download');await page.locator('#modal-content button', {hasText:'Скачать .ZIP'}).click();const download=await downloadEvent;assert.equal(download.suggestedFilename(),'tg-order-10482.zip');
  await page.locator('#close-modal').click();await page.locator('#workspace-toggle').click();
  const frame=page.frameLocator('#admin-workspace-frame');await frame.locator('.control-grid').waitFor();assert.equal(await frame.locator('.control-category').count(),4);assert.equal(await frame.locator('.control-action').count(),20);
  assert.equal(await frame.locator('body').evaluate(e=>document.documentElement.scrollWidth<=innerWidth),true,'admin horizontal overflow at '+width);
  await page.screenshot({path:path.join(artifacts,'tg-market-admin-'+width+'.png'),fullPage:true});
  if(width===1440){
   // Every control opens a real section or dialog; no fake success mutations.
   for(let i=0;i<20;i++){
    await frame.locator('.control-action').nth(i).click();await page.waitForTimeout(80);
    const dialog=frame.locator('#editor');if(await dialog.isVisible())await frame.locator('#cancel').click();
    const overview=frame.locator('nav [data-page=overview]');await overview.click();await frame.locator('.control-grid').waitFor();
   }
  }
  await page.locator('#workspace-toggle').click();await page.locator('#market').waitFor({state:'visible'});
  await context.close();
 }
 assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,viewports:[320,360,390,768,1440],previews,buys,adminActions:20,screenshots:artifacts}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
