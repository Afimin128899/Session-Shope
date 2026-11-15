/* Offline owner/helper/visitor UI checks. API authority is tested separately. */
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..'),token='a'.repeat(22),artifact='/tmp/sband-advertising';fs.mkdirSync(artifact,{recursive:true});
(async()=>{
 const browser=await chromium.launch({executablePath:'/usr/bin/chromium',args:['--no-sandbox']}),errors=[];
 try{for(const width of [320,390,1440])for(const role of ['helper','owner','visitor']){
  const context=await browser.newContext({viewport:{width,height:900}});let campaignName='<img src=x onerror=alert(1)>',revoked=false,created=0,staff=[{id:44,username:'helper44'}],copied='';const requests=[];
  await context.addInitScript(()=>{window.Telegram={WebApp:{initData:'fixture',ready(){},expand(){}}};Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{window.clipboardValue=text;}}});});
  await context.route('**/*',async route=>{
   const req=route.request(),u=new URL(req.url()),p=u.pathname;
   if(u.hostname!=='sband.test')return route.abort();
   if(p.startsWith('/api/')){
    requests.push(p);let data;
    if(p==='/api/admin/identity')return route.fulfill({status:role==='visitor'?403:200,json:role==='visitor'?{error:'Доступ запрещён'}:{is_admin:role==='owner',is_helper:role==='helper',user:{id:42,username:'fixture'}}});
    if(role==='helper'&&!p.startsWith('/api/admin/advertising'))throw Error('Helper requested owner data: '+p);
    if(revoked)return route.fulfill({status:403,json:{error:'Роль помощника снята'}});
    if(p==='/api/admin/advertising'){
     if(req.method()==='POST'){created++;assert.equal(req.postDataJSON().name,'Реклама канала');data={id:8,token};}
     else data={bot_username:'fixture_bot',items:[{id:7,name:campaignName,token,users_count:17},...(created?[{id:8,name:'Реклама канала',token,users_count:0}]:[])]};
    }else if(p==='/api/admin/advertising/7/users')data={campaign:{id:7,name:'Реклама'},items:[{user_id:u.searchParams.get('page')==='1'?78:77,username:'visitor',created_at:'2026-11-15 09:00:00'}],has_more:!u.searchParams.get('page')||u.searchParams.get('page')==='0'};
    else if(p==='/api/admin/helpers'){
     if(req.method()==='POST'){const b=req.postDataJSON();assert.equal(typeof b.enabled,'boolean');if(b.enabled)staff.push({id:b.user_id,username:null});else staff=staff.filter(x=>x.id!==b.user_id);}
     data={items:staff};
    }else if(p==='/api/admin/overview')data={stock:0,orders:0,users:0,approvals:0};
    else throw Error('Unexpected request '+p);
    return route.fulfill({json:data});
   }
   let file=p==='/admin-app'?'miniapp/admin_static/index.html':p.startsWith('/admin-assets/')?'miniapp/admin_static/'+p.slice(14):p.startsWith('/assets/')?'miniapp/static/'+p.slice(8):null;
   if(!file)return route.fulfill({status:404});const ext=path.extname(file);return route.fulfill({body:fs.readFileSync(path.join(root,file)),contentType:{'.html':'text/html','.js':'application/javascript','.css':'text/css','.png':'image/png','.svg':'image/svg+xml'}[ext]});
  });
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));await page.goto('https://sband.test/admin-app');
  if(role==='visitor'){await page.getByText('Доступ запрещён',{exact:true}).waitFor();assert.equal(await page.locator('#app').isVisible(),false);}
  if(role==='helper'){
   await page.getByRole('heading',{name:'Реклама',exact:true}).waitFor();assert.equal(await page.locator('nav button:visible').count(),1);assert.equal(await page.locator('nav button:visible').innerText(),'Реклама');
   assert.equal(await page.locator('.ad-campaign img').count(),0);assert((await page.locator('.ad-campaign h3').innerText()).includes('<img'));campaignName='Telegram · Канал A';
   await page.getByRole('button',{name:'Копировать ссылку',exact:true}).click();assert.equal(await page.evaluate(()=>window.clipboardValue),'https://t.me/fixture_bot?start=ad_'+token);
   await page.getByRole('button',{name:'Создать рекламную ссылку',exact:true}).click();await page.getByLabel('Название рекламы',{exact:true}).fill('Реклама канала');await page.getByRole('button',{name:'Сохранить',exact:true}).click();await page.getByRole('heading',{name:'Реклама канала',exact:true}).waitFor();assert.equal(created,1);
   await page.locator('.ad-campaign').first().getByRole('button',{name:'Пользователи',exact:true}).click();await page.getByText('77',{exact:true}).waitFor();await page.getByRole('button',{name:'Далее',exact:true}).click();await page.getByText('78',{exact:true}).waitFor();await page.getByRole('button',{name:'Все рекламные ссылки',exact:true}).click();
   await page.getByRole('heading',{name:'Реклама',exact:true}).waitFor();if(width===390)await page.screenshot({path:artifact+'/helper.png',fullPage:true});
   revoked=true;await page.getByRole('button',{name:'Реклама',exact:true}).click();await page.getByText('Роль помощника снята',{exact:true}).waitFor();assert.equal(await page.locator('.ad-campaign').count(),0);
  }
  if(role==='owner'){
   await page.getByRole('heading',{name:'Обзор',exact:true}).waitFor();assert.equal(await page.locator('[data-page=advertising]').isVisible(),false);
   await page.getByRole('button',{name:'Помощник',exact:true}).click();await page.getByRole('button',{name:'Назначить помощника',exact:true}).click();await page.getByLabel('Telegram ID',{exact:true}).fill('45');await page.getByRole('button',{name:'Сохранить',exact:true}).click();await page.getByText('45',{exact:true}).waitFor();
   await page.locator('.row').filter({has:page.getByText('44',{exact:true})}).getByRole('button',{name:'Снять роль',exact:true}).click();await page.getByLabel('Введите Telegram ID для подтверждения',{exact:true}).fill('44');await page.getByRole('button',{name:'Сохранить',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('#editor').open);assert.deepEqual(staff.map(x=>x.id),[45]);
  }
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'overflow '+role+' '+width);await context.close();
 }
 assert.deepEqual(errors,[]);console.log('PASS: helper-only advertising, owner role management, copy/create/users/pagination/revocation and safe text at 320/390/1440');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
