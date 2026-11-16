/* Offline browser fixtures: scoped admin controls, cash/bonus display and main-bot funding. */
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..'),artifacts='/tmp/sband-partners';fs.mkdirSync(artifacts,{recursive:true});
(async()=>{
 const browser=await chromium.launch({executablePath:'/usr/bin/chromium',args:['--no-sandbox']}),errors=[];
 try{for(const width of [320,390,1440])for(const role of ['partner','owner','customer']){
  const context=await browser.newContext({viewport:{width,height:900}});let bans=[],content={},status='pending';const requests=[];
  await context.addInitScript(()=>{window.Telegram={WebApp:{initData:'fixture',ready(){},expand(){},setHeaderColor(){},setBackgroundColor(){}}};});
  await context.route('**/*',async route=>{
   const req=route.request(),url=new URL(req.url()),p=url.pathname;
   if(url.hostname!=='sband.test')return route.abort();
   if(p.startsWith('/api/')){
    requests.push(p);if(role!=='owner')assert.equal(req.headers()['x-partner-id'],'777001',p);
    let data;
    if(p==='/api/admin/identity')data={is_admin:role==='owner',is_partner_owner:role==='partner',user:{id:42,username:'fixture'}};
    else if(role==='partner'){
     assert(['/api/admin/partner-bans','/api/admin/partner-content'].includes(p),'Partner requested privileged data '+p);
     if(p.endsWith('partner-bans')){if(req.method()==='POST')bans=[{...req.postDataJSON(),active:1}];data={items:bans};}
     else {if(req.method()==='POST'){const b=req.postDataJSON();content[b.key]=b.value;}data={content,labels:['btn_buy']};}
    }else if(p==='/api/admin/overview')data={stock:0,orders:0,users:0,approvals:0};
    else if(p==='/api/admin/partners'){if(req.method()==='POST')status=req.postDataJSON().action==='enable'?'enabled':'closed';data={items:[{bot_id:777001,owner_id:42,username:'fixture_partner',status}]};}
    else if(p==='/api/me')data={user:{id:42,first_name:'Fixture'},balance:350,cash_balance:300,bonus_balance:50,partner_id:777001,bot_username:'main_fixture_bot'};
    else if(p==='/api/avatar')return route.fulfill({status:404});
    else if(p==='/api/category-market')data={items:[]};
    else if(p==='/api/wallet/summary')data={deposited:300,spent:0,purchase_count:0};
    else throw Error('Unexpected API '+p);
    return route.fulfill({json:data});
   }
   const file=p==='/'?'miniapp/storefront_v2/index.html':p==='/admin-app'?'miniapp/admin_static/index.html':p.startsWith('/admin-assets/')?'miniapp/admin_static/'+p.slice(14):p.startsWith('/store-assets/')?'miniapp/storefront_v2/'+p.slice(14):p.startsWith('/assets/')?'miniapp/static/'+p.slice(8):null;
   if(!file||!fs.existsSync(path.join(root,file)))return route.fulfill({status:404});
   return route.fulfill({body:fs.readFileSync(path.join(root,file)),contentType:{'.html':'text/html','.js':'application/javascript','.css':'text/css','.png':'image/png','.svg':'image/svg+xml'}[path.extname(file)]});
  });
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
  if(role==='customer'){
   await page.goto('https://sband.test/?partner=777001');await page.locator('#wallet').filter({hasText:'350'}).waitFor();
   await page.locator('[data-tab=profile]').click();await page.locator('#wallet-cash').filter({hasText:'300'}).waitFor();assert((await page.locator('#wallet-bonus').innerText()).includes('50'));
   await page.locator('#topup').click();assert.equal(await page.getByRole('link',{name:'Открыть основной бот'}).getAttribute('href'),'https://t.me/main_fixture_bot?start=fund_777001');assert(!requests.includes('/api/payment-methods'));
  }else{
   await page.goto('https://sband.test/admin-app'+(role==='partner'?'?partner=777001':''));
   if(role==='partner'){
    await page.getByRole('heading',{name:'Общие блокировки',exact:true}).waitFor();assert.equal(await page.locator('nav button:visible').count(),2);
    await page.getByRole('button',{name:'Заблокировать пользователя',exact:true}).click();await page.getByLabel('Telegram ID',{exact:true}).fill('55');await page.getByLabel('Причина',{exact:true}).fill('<img src=x onerror=alert(1)>');await page.getByRole('button',{name:'Сохранить',exact:true}).click();await page.getByText('55',{exact:true}).waitFor();assert.equal(await page.locator('#content img').count(),0);
    await page.getByRole('button',{name:'Оформление бота',exact:true}).click();await page.getByRole('heading',{name:'Оформление бота',exact:true}).waitFor();
    await page.locator('.row').filter({has:page.getByText('Каталог',{exact:true})}).getByRole('button',{name:'Изменить'}).click();await page.getByLabel('Подпись до 50 символов',{exact:true}).fill('Мой магазин');await page.getByRole('button',{name:'Сохранить',exact:true}).click();await page.getByText('Мой магазин',{exact:true}).waitFor();assert.equal(content.btn_buy,'Мой магазин');
   }else{
    await page.getByRole('button',{name:'Партнёрские боты',exact:true}).click();await page.getByText('@fixture_partner',{exact:true}).waitFor();await page.getByRole('button',{name:'Одобрить и включить',exact:true}).click();await page.getByText('enabled',{exact:true}).waitFor();if(width===390)await page.screenshot({path:artifacts+'/owner.png',fullPage:true});
    await page.getByRole('button',{name:'Закрыть и вернуть остатки',exact:true}).click();await page.getByLabel('Введите ID бота 777001 для закрытия и возврата внесённых остатков',{exact:true}).fill('777001');await page.getByRole('button',{name:'Сохранить',exact:true}).click();await page.getByText('closed',{exact:true}).waitFor();
   }
  }
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,role+' overflow '+width);
  if(width===390&&role!=='owner')await page.screenshot({path:artifacts+'/'+role+'.png',fullPage:true});
  await context.close();
 }assert.deepEqual(errors,[]);console.log('PASS: partner moderation/branding, strict scoped requests, main approval/close, cash and bonus display, main-bot-only topups at 320/390/1440');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
