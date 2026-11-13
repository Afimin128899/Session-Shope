/* Offline UI regression. NODE_PATH=<playwright installation> node tests/ui_polish_browser.cjs */
const { chromium } = require('playwright');
const fs = require('fs'), path = require('path'), assert = require('assert');
const root = path.resolve(__dirname, '..');
const artifacts = process.env.SBAND_UI_ARTIFACTS || '/tmp/sband-ui';
fs.mkdirSync(artifacts, { recursive: true });
(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', args: ['--no-sandbox'] });
  const errors = []; const widths = [320,390,768,1440];
  for (const width of widths) {
    const context = await browser.newContext({ viewport: { width, height: 900 } });
    let buyCount=0, failCatalog=false, failPrice=false, priceCount=0, deleted=[], queued=[], chats=[], codeCount=0;
    let stock=[1,2,3].map((id)=>({id,country:id===3?'auto-ca-clear':'auto-us-clear',name:id===3?'Канада Без спамблока':'США Без спамблока',number:'+1555111000'+id,price:99,status:'available',registration_date:'2021-04-12',spam_check:{label:'Ограничений не обнаружено'}}));
    await context.addInitScript(()=>{Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async value=>{window.fixtureClipboard=value;}}});window.Telegram={WebApp:{initData:'offline-fixture',ready(){},expand(){},setHeaderColor(){},setBackgroundColor(){},openInvoice(url){window.fixtureInvoice=url},openLink(url){window.fixtureLink=url}}};});
    await context.route('**/*',async route=>{
      const request=route.request(),url=new URL(request.url()),p=url.pathname;
      if(url.hostname==='telegram.org')return route.fulfill({body:'',contentType:'application/javascript'});
      if(p.startsWith('/api/')){
        let data;
        if(p==='/api/me')data={user:{id:42,first_name:'Александр',username:'alex',photo_url:'/assets/sband.png'},balance:1250,is_admin:true,bot_username:'SbandACCSbot'};
        else if(p==='/api/category-market'){
          if(failCatalog){failCatalog=false;return route.fulfill({status:503,json:{error:'Каталог временно недоступен.'}});}
          data={items:url.searchParams.has('country')?[{country:'us',nation:'us~clear',name:'США Без спамблока',count:12,min_price:74},{country:'us',nation:'us~permanent',name:'США Вечный СБ',count:5,min_price:59},{country:'us',nation:'us~unverified',name:'США',count:8,min_price:50}]:[{country:'us',name:'США',count:25,min_price:50},{country:'ca',name:'Канада',count:8,min_price:99},{country:'jp',name:'Япония',count:5,min_price:199},{country:'kz',name:'Казахстан',count:4,min_price:229}]};
        }else if(p==='/api/category-quote')data={token:'fixture',name:'США Без спамблока',price:74,warranty_hours:24};
        else if(p==='/api/category-buy'){buyCount++;await new Promise(r=>setTimeout(r,180));data={id:11};}
        else if(p==='/api/orders/11')data={id:11,status:'issued',status_label:'Выдан',number:'+15551112222',password:'fixture-password'};
        else if(p==='/api/orders/11/code')data=++codeCount===1?{status:'pending',message:'Код пока не пришёл.'}:{status:'ready',code:'12345'};
        else if(p==='/api/wallet/summary')data={deposited:1600,spent:350,purchase_count:8};
        else if(p==='/api/referrals')data={count:7,earned:'21',bot_username:'SbandACCSbot'};
        else if(p==='/api/payment-methods')data={items:[{id:'crypto',name:'Crypto Pay',enabled:true,min:10,max:10000},{id:'stars',name:'Telegram Stars',enabled:true,min:1,max:8333},{id:'heleket',name:'Heleket',enabled:false,min:50,max:10000}]};
        else if(p==='/api/invoices')return route.fulfill({status:409,json:{error:'Платёжный сервис временно недоступен.'}});
        else if(p==='/api/promo/redeem')return route.fulfill({status:400,json:{error:'Промокод не найден.'}});
        else if(p==='/api/chat'){
          if(request.method()==='POST')chats.push({id:chats.length+1,author_role:'user',body:request.postDataJSON().body,created_at:'2026-11-13 10:00:00'});
          data={items:chats,has_more:false};
        }else if(p==='/api/admin/identity')data={is_admin:true,user:{id:42,username:'alex'}};
        else if(p==='/api/admin/overview')data={stock:37,orders:128,users:246,approvals:2};
        else if(p==='/api/admin/stock')data={items:stock,has_more:false};
        else if(p==='/api/admin/stock/bulk'){
          priceCount++;if(failPrice){failPrice=false;return route.fulfill({status:400,json:{error:'Проверьте цену.'}});}data={ok:true};
        }else if(p.match(/\/api\/admin\/stock\/\d+\/spam-check/)){queued.push(Number(p.split('/')[4]));await new Promise(r=>setTimeout(r,100));data={queued:1};}
        else if(p.match(/\/api\/admin\/stock\/\d+$/)&&request.method()==='DELETE'){const id=Number(p.split('/')[4]);deleted.push(id);stock=stock.filter(x=>x.id!==id);data={ok:true};}
        else if(p==='/api/admin/categories')data={items:[{slug:'auto-us-clear',name:'США Без спамблока',is_active:1}]};
        else if(p==='/api/admin/categories/price')data={updated:2};
        else throw Error('Unexpected API '+p);
        return route.fulfill({json:data});
      }
      let file;
      if(p==='/')file='miniapp/storefront_v2/index.html';
      else if(p==='/admin-app')file='miniapp/admin_static/index.html';
      else if(p.startsWith('/store-assets/'))file='miniapp/storefront_v2/'+p.slice('/store-assets/'.length);
      else if(p.startsWith('/admin-assets/'))file='miniapp/admin_static/'+p.slice('/admin-assets/'.length);
      else if(p.startsWith('/assets/'))file='miniapp/static/'+p.slice('/assets/'.length);
      if(!file)return route.fulfill({status:404,body:''});
      const ext=path.extname(file);await route.fulfill({body:fs.readFileSync(path.join(root,file)),contentType:({'.html':'text/html','.js':'application/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png'})[ext]||'application/octet-stream'});
    });
    const page=await context.newPage();page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push(e.message));
    const noOverflow=async()=>assert(!await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),'Overflow at '+width+' '+page.url());
    const screen=async name=>{await page.evaluate(()=>{scrollTo(0,0);const toast=document.querySelector('#toast');if(toast)toast.hidden=true;});await page.waitForTimeout(250);await noOverflow();if([390,1440].includes(width))await page.screenshot({path:path.join(artifacts,name+'-'+width+'.png'),fullPage:true});};
    const close=async()=>{await page.getByRole('button',{name:'Закрыть',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('#modal').open);};
    await page.goto('http://sband.test/');await page.locator('.category').first().waitFor();
    await page.waitForFunction(()=>[...document.querySelectorAll('.country-avatar img')].every(i=>i.complete));
    await screen('market');assert.equal(await page.locator('.bottom-nav').evaluate(n=>getComputedStyle(n).position),'fixed','Navigation must stay fixed');
    await page.getByRole('button',{name:'Бесплатный аккаунт',exact:true}).click();
    await page.getByText('7 / 10',{exact:true}).waitFor();await screen('free-account');await page.getByRole('button',{name:'Скопировать ссылку',exact:true}).click();assert.equal(await page.evaluate(()=>window.fixtureClipboard),'https://t.me/SbandACCSbot?start=ref_42');assert.equal(await page.locator('.referral-progress progress').getAttribute('value'),'7');
    await page.getByRole('button',{name:'Написать в поддержку',exact:true}).click();await page.getByRole('textbox',{name:'Сообщение поддержке'}).waitFor();assert((await page.getByRole('textbox',{name:'Сообщение поддержке'}).inputValue()).includes('10 рефералов'));assert.equal(chats.length,0,'Support message sent without submit');
    await page.getByRole('button',{name:'Маркет',exact:true}).click();await page.locator('.category').first().waitFor();
    const navBefore=await page.locator('.bottom-nav .selection-track').getAttribute('style');
    if(width===390){await page.locator('[data-mode=auto]').hover();await page.mouse.down();assert(await page.evaluate(()=>document.getAnimations().some(a=>a.playState==='running')),'Press animation missing');await page.mouse.up();await page.waitForFunction(()=>document.querySelectorAll('.category').length===4);}

    failCatalog=true;await page.getByRole('button',{name:'С отлегой',exact:true}).click();await page.getByRole('button',{name:'Повторить',exact:true}).click();await page.locator('.category').first().waitFor();
    await page.locator('.category').filter({has:page.getByRole('heading',{name:'США',exact:true})}).getByRole('button',{name:'Категории',exact:true}).click();
    await page.locator('.category').first().getByRole('button',{name:'Купить',exact:true}).click();
    await page.getByRole('button',{name:'Купить за 74,00 ₽',exact:true}).evaluate(b=>{b.click();b.click();});
    await page.getByRole('button',{name:'Получить код',exact:true}).waitFor();assert.equal(buyCount,1,'Duplicate purchase');
    await page.getByRole('button',{name:'Получить код',exact:true}).click();await page.getByText('Код пока не пришёл.',{exact:true}).waitFor();await page.getByRole('button',{name:'Получить код',exact:true}).click();await page.locator('.login-code').waitFor();await close();
    await page.getByRole('button',{name:'Профиль',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#purchased').textContent==='8');await screen('profile');assert.notEqual(await page.locator('.bottom-nav .selection-track').getAttribute('style'),navBefore,'Navigation indicator did not move');
    await page.getByRole('button',{name:'Ввести промокод',exact:false}).click();await page.getByRole('button',{name:'Активировать',exact:true}).click();await page.getByText('Введите промокод.',{exact:true}).waitFor();await page.getByLabel('Промокод',{exact:true}).fill('BAD');await page.getByRole('button',{name:'Активировать',exact:true}).click();await page.getByText('Промокод не найден.',{exact:true}).waitFor();assert.equal(await page.getByLabel('Промокод',{exact:true}).inputValue(),'BAD');await close();
    await page.getByRole('button',{name:'Пополнить баланс',exact:true}).click();const amount=page.getByLabel('Сумма, ₽',{exact:true});await amount.fill('bad');await page.getByRole('button',{name:'Перейти к оплате',exact:true}).click();await page.getByText('Введите корректное положительное число.',{exact:true}).waitFor();await amount.fill('100');await page.getByRole('button',{name:'Перейти к оплате',exact:true}).click();await page.getByText('Платёжный сервис временно недоступен.',{exact:true}).waitFor();assert.equal(await amount.inputValue(),'100');await screen('topup');await close();
    await page.getByRole('button',{name:'Сообщения',exact:true}).click();await page.getByRole('textbox',{name:'Сообщение поддержке'}).fill('Здравствуйте! Нужна помощь с покупкой.');await page.getByRole('button',{name:'Отправить',exact:true}).click();await page.locator('.bubble.mine').waitFor();await noOverflow();
    await page.goto('http://sband.test/admin-app');await page.getByRole('heading',{name:'Обзор',exact:true}).waitFor();await screen('dashboard');await page.getByRole('button',{name:'Товары',exact:true}).click();await page.getByRole('combobox',{name:'Статус товара'}).selectOption('available');await page.getByRole('checkbox',{name:'Выбрать товар #1',exact:true}).check();await page.getByRole('checkbox',{name:'Выбрать товар #2',exact:true}).check();await screen('admin');assert(await page.locator('.stock-select input').first().evaluate(e=>e.getBoundingClientRect().width<=25),'Selection checkbox expanded');
    await page.getByRole('button',{name:'Изменить цену',exact:true}).click();await page.getByLabel('Новая цена, ₽').fill('79');failPrice=true;await page.getByRole('button',{name:'Сохранить',exact:true}).click();await page.locator('#form-error').getByText('Обработано: 0 из 2. Проверьте цену.',{exact:true}).waitFor();assert.equal(await page.getByLabel('Новая цена, ₽').inputValue(),'79');await page.getByRole('button',{name:'Сохранить',exact:true}).click();await page.getByText('Обработано товаров: 2',{exact:true}).waitFor();assert.equal(priceCount,2);
    await page.getByRole('checkbox',{name:'Выбрать товар #1',exact:true}).check();await page.getByRole('button',{name:'Удалить выбранные',exact:true}).click();await page.getByRole('heading',{name:'Удалить выбранные товары: 1',exact:true}).waitFor();assert.equal(deleted.length,0);await page.getByLabel('Для удаления введите УДАЛИТЬ').fill('УДАЛИТЬ');await page.locator('#editor').getByRole('button',{name:'Удалить выбранные',exact:true}).click();await page.getByText('Обработано товаров: 1',{exact:true}).waitFor();assert.deepEqual(deleted,[1]);
    await page.getByRole('checkbox',{name:'Выбрать товар #2',exact:true}).check();await page.getByRole('button',{name:'Проверить спамблок',exact:true}).click();await page.getByText(/Поставлено в очередь: 1 из 1/).waitFor();assert.deepEqual(queued,[2]);
    await page.getByRole('button',{name:'Категории',exact:true}).click();await page.getByRole('button',{name:'Цена всех товаров',exact:true}).click();await page.getByLabel('Новая цена всех непроданных товаров категории, ₽').fill('89');await page.getByRole('button',{name:'Сохранить',exact:true}).click();await page.getByText('Цена обновлена. Изменено товаров: 2',{exact:true}).waitFor();
    if(width===390){await page.emulateMedia({reducedMotion:'reduce'});await page.getByRole('button',{name:'Товары',exact:true}).click();await page.waitForTimeout(250);assert.equal(await page.evaluate(()=>document.getAnimations().filter(a=>a.playState==='running').length),0,'Reduced motion ignored');}
    await noOverflow();await context.close();
  }
  assert.deepEqual(errors,[]);await browser.close();console.log(JSON.stringify({viewports:widths,purchase:true,loginCode:true,topup:true,chat:true,selection:true,price:true,categoryPrice:true,delete:true,freeAccount:true,reducedMotion:true,errors,artifacts}));
})().catch(e=>{console.error(e);process.exit(1);});
