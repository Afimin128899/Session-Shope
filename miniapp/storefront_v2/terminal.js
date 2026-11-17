/* Live marketplace workspace. All prices, stock and mutations come from authenticated APIs. */
(()=>{
 'use strict';
 const countries=[['us','🇺🇸','США','+1'],['gb','🇬🇧','Великобритания','+44'],['de','🇩🇪','Германия','+49'],['kz','🇰🇿','Казахстан','+7'],['id','🇮🇩','Индонезия','+62'],['pl','🇵🇱','Польша','+48']];
 document.querySelectorAll('.trust-icon').forEach((n,i)=>n.replaceChildren(SbandUI.icon(['arrowUp','search','info','history'][i])));
 document.querySelector('.summary-symbol').replaceChildren(SbandUI.icon('arrowUp'));
 const config={country:'us',age:7,premium:false,two_fa:false,clear:true,quantity:1,format:'session',preview:null,revision:0};
 const ages={7:'7+ дней',30:'1+ месяц',180:'6+ месяцев',365:'1+ год'};
 let previewTimer,guest=false;
 const query=()=>({country:config.country,age:config.age,premium:config.premium,two_fa:config.two_fa,clear:config.clear});
 for(const [code,flag,name,dial] of countries){
  const b=btn('',()=>{config.country=code;requestPreview();},'geo-option');b.dataset.geo=code;b.setAttribute('aria-pressed',String(code===config.country));
  b.append(el('span',flag,'geo-flag'),el('strong',name),el('small',dial));$('geo-options').append(b);
 }
 function render(){
  const country=countries.find(c=>c[0]===config.country);$('config-country').textContent=country[2]+' '+country[3];
  $('config-spec').textContent=(config.format==='session'?'Session + JSON':'Вход по коду')+' · '+ages[config.age];
  document.querySelectorAll('[data-geo]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.geo===config.country)));
  document.querySelectorAll('[data-age]').forEach(b=>b.setAttribute('aria-pressed',String(Number(b.dataset.age)===config.age)));
  document.querySelectorAll('[data-quantity]').forEach(b=>b.setAttribute('aria-pressed',String(Number(b.dataset.quantity)===config.quantity)));
  $('config-tags').replaceChildren();for(const [enabled,label] of [[config.clear,'Без спамблока'],[config.premium,'✦ Premium'],[config.two_fa,'Пароль 2FA']])if(enabled)$('config-tags').append(el('span',label));
  const data=config.preview,selected=data?.quantities.find(q=>q.quantity===config.quantity),valid=Boolean(selected)&&Number.isInteger(config.quantity)&&config.quantity>0&&config.quantity<=20;
  $('config-stock').textContent=data?Number(data.count).toLocaleString('ru-RU')+' шт.':'— шт.';
  $('config-price').textContent=data?.unit_price?money(data.unit_price):'— ₽';
  $('config-total').textContent=valid?money(selected.total):'— ₽';
  $('config-checkout').disabled=!valid||guest;
  $('config-checkout').textContent=guest?'Откройте магазин в Telegram':valid?'Оформить заказ · '+money(selected.total):data?'Нет подходящих аккаунтов':'Проверяем наличие…';
  if(data){$('config-bulk').textContent='Опт: −'+data.wholesale.percent+'% от '+money(data.wholesale.minimum)+(selected&&Number(selected.rate)>0?' · скидка применена':'');$('config-feedback').textContent=valid?'Точная сумма и срок гарантии — на следующем шаге.':'Попробуйте другую страну или измените характеристики.';}
  const max=Math.min(data?.count??20,20);$('config-quantity').max=String(Math.max(max,1));
  $('quantity-minus').disabled=!(config.quantity>1);$('quantity-plus').disabled=!(config.quantity<max);
  document.querySelectorAll('[data-quantity]').forEach(b=>b.disabled=Number(b.dataset.quantity)>max);
 }
 async function refreshPreview(){
  const revision=++config.revision;config.preview=null;render();
  try{
   const data=await api('configurator/preview',query());if(revision!==config.revision)return;
   config.preview=data;guest=false;
   if(config.quantity>Math.min(data.count,20)&&data.count>0){config.quantity=Math.min(data.count,20);$('config-quantity').value=config.quantity;}
   render();
  }catch(e){if(revision!==config.revision)return;$('config-feedback').textContent=clean(e.message);$('config-checkout').textContent='Обновить наличие';$('config-checkout').disabled=false;}
 }
 function requestPreview(){++config.revision;config.preview=null;render();clearTimeout(previewTimer);previewTimer=setTimeout(refreshPreview,180);}
 document.querySelectorAll('[data-age]').forEach(b=>b.addEventListener('click',()=>{config.age=Number(b.dataset.age);requestPreview();}));
 for(const [id,key] of [['config-clear','clear'],['config-premium','premium'],['config-twofa','two_fa']])$(id).addEventListener('change',()=>{config[key]=$(id).checked;requestPreview();});
 document.querySelectorAll('[name=delivery-format]').forEach(r=>r.addEventListener('change',()=>{config.format=r.value;render();}));
 function setQuantity(value){config.quantity=value;$('config-quantity').value=value;render();}
 $('quantity-minus').onclick=()=>setQuantity(Math.max(1,config.quantity-1));$('quantity-plus').onclick=()=>setQuantity(Math.min(20,config.quantity+1));
 $('config-quantity').addEventListener('input',()=>{config.quantity=Number($('config-quantity').value);render();});
 $('config-quantity').addEventListener('change',()=>{if(!Number.isInteger(config.quantity)||config.quantity<1||config.quantity>20)setQuantity(Math.min(20,Math.max(1,Math.floor(config.quantity)||1)));});
 document.querySelectorAll('[data-quantity]').forEach(b=>b.addEventListener('click',()=>setQuantity(Number(b.dataset.quantity))));
 async function downloadArchive(id,button){
  {
   const r=await fetch('/api/orders/'+id+'/archive',{headers:{...SbandUI.scopeHeaders(),Authorization:'tma '+(tg?.initData||'')},cache:'no-store'});
   if(!r.ok){const error=await r.json();throw Error(error.error||'Архив недоступен.');}
   const blob=await r.blob(),url=URL.createObjectURL(blob),a=el('a');a.href=url;a.download='tg-order-'+id+'.zip';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);toast('Архив заказа #'+id+' подготовлен');
  }
 }
 async function checkout(){
  if(!config.preview){await refreshPreview();return;}
  if(!Number.isInteger(config.quantity)||config.quantity<1||config.quantity>20)throw Error('Количество: от 1 до 20.');
  const selectedCountry=countries.find(c=>c[0]===config.country),format=config.format;
  const quote=await api('configurator/quote',{...query(),quantity:config.quantity});
  const body=open('Подтвердите покупку'),summary=el('div',undefined,'checkout-confirmation');
  row(summary,selectedCountry[1]+' '+selectedCountry[2],ages[config.age]+' · '+(format==='session'?'Session + JSON':'Вход по коду'));
  row(summary,'Количество',String(quote.quantity)+' шт.');row(summary,'Оптовая скидка',String(quote.rate)+'%');
  row(summary,'Гарантия',quote.warranty_hours.map(h=>h>0?h+' ч.':'Без гарантии').join(' / '));
  const total=el('div',undefined,'checkout-total');total.append(el('span','К оплате'),el('strong',money(quote.total)));summary.append(total);body.append(summary);
  body.append(el('p','Резерв действует 5 минут. Получатель: '+(state.me?.user.username?'@'+state.me.user.username:'Telegram ID '+state.me?.user.id)+'. Данные сохранятся в личном кабинете.','muted'));
  const routes=el('div'),feedback=el('p','','checkout-feedback');feedback.setAttribute('role','status');body.append(routes);
  let method='balance';
  const pay=btn('Оплатить с баланса · '+money(quote.total),async()=>{
   if(Date.now()/1000>=quote.expires_at){feedback.textContent='Резерв истёк. Закройте окно и подберите аккаунты заново.';return;}
   if(method!=='balance'){await topup();return;}
   try{
    const result=await api('configurator/buy',{token:quote.token});
    const success=open('Заказ оплачен');success.append(el('div','✓','checkout-success'),el('h3','Аккаунты готовы к выдаче'),el('p','Оплачено '+money(result.paid_amount)+'. Заказы сохранены в профиле.','muted'));
    for(const id of result.order_ids){
     const actions=el('div',undefined,'actions');actions.append(btn('Заказ #'+id,()=>order(id),'subtle'));
     if(format==='session'){const download=btn('Скачать .ZIP',()=>downloadArchive(id,download),'primary');actions.append(download);}
     success.append(actions);
    }
    await me().catch(()=>toast('Покупка сохранена. Обновите баланс в профиле.'));market().catch(()=>{});
   }catch(e){feedback.textContent=clean(e.message);}
  },'primary full');
  function route(value,title,note){const l=el('label',undefined,'payment-route'),radio=el('input');radio.type='radio';radio.name='checkout-payment';radio.value=value;radio.checked=value==='balance';l.append(radio,el('span',title),el('small',note));radio.addEventListener('change',()=>{method=value;pay.textContent=value==='balance'?'Оплатить с баланса · '+money(quote.total):'Пополнить баланс';});routes.append(l);}
  route('balance','Баланс магазина',money(state.me?.balance));route('topup','Криптовалюта / карта','Доступные способы пополнения');
  body.append(pay,feedback,el('p','Нажимая «Оплатить», вы принимаете условия магазина. Проверка наличия и списание выполняются атомарно.','muted'));
 }
 $('config-checkout').onclick=()=>SbandUI.run($('config-checkout'),checkout).catch(e=>toast(e.message));
 // Same-origin iframe retains the existing admin shell and its authorization boundaries.
 const originalNavigate=navigate;
 navigate=async function(tab){
  if(tab!=='admin-workspace'){$('workspace-toggle').setAttribute('aria-pressed','false');return originalNavigate(tab);}
  if(!state.me?.is_admin&&!state.me?.is_helper&&!state.me?.is_partner_owner)return;
  clearTimeout(state.searchTimer);++state.revision;state.tab=tab;
  document.querySelectorAll('.page').forEach(p=>p.hidden=p.id!==tab);
  document.querySelectorAll('[data-tab]').forEach(b=>{b.classList.remove('selected');b.removeAttribute('aria-current');});
  $('workspace-toggle').setAttribute('aria-pressed','true');
  if(!$('admin-workspace-frame').getAttribute('src')){const target=new URL('/admin-app'+location.search,location.origin);target.searchParams.set('embedded','1');$('admin-workspace-frame').src=target.pathname+target.search;}
  window.scrollTo({top:0,behavior:'instant'});
 };
 window.addEventListener('message',event=>{if(event.origin===location.origin&&event.source===$('admin-workspace-frame').contentWindow&&event.data?.type==='tg-market:admin-modal')$('admin-workspace-frame').scrollIntoView({block:'start',behavior:'instant'});});
 document.querySelectorAll('.top-links a').forEach(a=>a.addEventListener('click',async event=>{if(state.tab!=='market'){event.preventDefault();await navigate('market');document.querySelector(a.getAttribute('href')).scrollIntoView({behavior:'smooth'});}}));
 $('workspace-toggle').onclick=()=>navigate(state.tab==='admin-workspace'?'market':'admin-workspace');
 $('admin-link').onclick=()=>navigate('admin-workspace');
 const originalOrder=order;
 order=async function(id){await originalOrder(id);const data=await api('orders/'+id);if(data.status==='issued'&&!data.access_revoked_at){const b=btn('Скачать Session + JSON',()=>downloadArchive(id,b),'subtle full');$('modal-content').append(b);}else if(data.access_revoked_at)$('modal-content').append(el('p','Доступ через магазин отозван. Обратитесь в поддержку по номеру заказа.','muted'));};
 function identityReady(){guest=false;$('telegram-login').hidden=true;$('workspace-toggle').hidden=!(state.me?.is_admin||state.me?.is_helper||state.me?.is_partner_owner);refreshPreview();}
 window.addEventListener('market:identity',identityReady);
 if(state.me)identityReady();else render();
 $('browse-accounts').onclick=()=>$('configurator').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
 document.querySelectorAll('[data-terminal-info]').forEach(b=>b.onclick=information);
 document.querySelectorAll('[data-terminal-support]').forEach(b=>b.onclick=()=>navigate('messages'));
 $('telegram-login').onclick=async()=>{try{const d=await api('app-info');if(!d.bot_username)throw Error('Откройте магазин из меню Telegram-бота.');const link='https://t.me/'+d.bot_username;tg?.openTelegramLink?tg.openTelegramLink(link):location.assign(link);}catch(e){toast(e.message);}};
 fetch('/api/health',{cache:'no-store'}).then(r=>{const status=$('api-status');status.classList.toggle('online',r.ok);status.replaceChildren(el('i'),document.createTextNode(r.ok?'API Online':'API недоступен'));}).catch(()=>$('api-status').textContent='API недоступен');
 setTimeout(()=>{if(!state.me){guest=true;render();$('telegram-login').hidden=false;$('config-feedback').textContent='Для просмотра наличия и покупки откройте Mini App из Telegram-бота.';}},5000);
 render();
})();
