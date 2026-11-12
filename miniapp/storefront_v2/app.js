'use strict';
const tg=window.Telegram?.WebApp,$=id=>document.getElementById(id);
const state={tab:'market',mode:'auto',country:null,revision:0,me:null,chatLast:0,invoice:null};
const money=value=>new Intl.NumberFormat('ru-RU',{style:'currency',currency:'RUB'}).format(Number(value||0));
const clean=value=>String(value||'').replace(/[\p{Extended_Pictographic}\p{Regional_Indicator}\uFE0F]/gu,'').trim();
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=String(text);if(cls)n.className=cls;return n;}
function toast(value){$('toast').textContent=clean(value);$('toast').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('toast').hidden=true,5000);}
function btn(text,action,cls=''){const b=el('button',text,cls);b.type='button';b.addEventListener('click',async()=>{if(b.disabled)return;b.disabled=true;try{await action();}catch(e){toast(e.message);}finally{b.disabled=false;}});return b;}
async function api(path,body){const r=await fetch('/api/'+path,{method:body===undefined?'GET':'POST',headers:{Authorization:'tma '+(tg?.initData||''),...(body!==undefined?{'Content-Type':'application/json'}:{})},body:body===undefined?undefined:JSON.stringify(body),cache:'no-store'});const d=await r.json();if(!r.ok)throw Error(d.error||'Не удалось выполнить запрос.');return d;}
function open(title){$('modal-title').textContent=title;$('modal-content').replaceChildren();if(!$('modal').open)$('modal').showModal();return $('modal-content');}
function row(parent,title,detail,action){const r=el('div',undefined,'row'),d=el('div');d.append(el('strong',title));if(detail)d.append(el('small',detail));r.append(d);if(action)r.append(action);parent.append(r);}
function label(parent,text,input){const l=el('label',text,'form-label');l.append(input);parent.append(l);return input;}
function empty(parent,text){parent.append(el('p',text,'empty'));}
function date(value){if(!value)return '';const iso=String(value).replace(' ','T');const d=new Date(/[Z+]\d*/.test(iso)?iso:iso+'Z');return Number.isNaN(+d)?String(value):d.toLocaleString('ru-RU');}
async function me(){
 state.me=await api('me');const user=state.me.user;
 $('wallet').textContent=money(state.me.balance);$('balance').textContent=money(state.me.balance);
 $('username').textContent=user.username?'@'+user.username:user.first_name;
 $('user-id').textContent='ID: '+user.id;$('admin-link').hidden=!state.me.is_admin;
 if(state.avatarOwner!==user.id){
  state.avatarOwner=user.id;$('avatar').textContent=(user.first_name||'S').slice(0,1).toUpperCase();
  async function loadPhoto(){
   let src=user.photo_url;
   if(!src){const r=await fetch('/api/avatar',{headers:{Authorization:'tma '+(tg?.initData||'')},cache:'no-store'});if(!r.ok)return;src=URL.createObjectURL(await r.blob());state.avatarObjectURL=src;}
   const image=el('img',undefined,'profile-photo');image.alt='Фото профиля Telegram';image.referrerPolicy='no-referrer';
   image.onload=()=>{if(state.avatarOwner===user.id)$('avatar').replaceChildren(image);};image.src=src;
  }
  loadPhoto().catch(()=>{});
 }
}
function countryAvatar(country,name){
 const frame=el('span',undefined,'country-avatar');const image=el('img');
 const code=/^[a-z]{2}$/.test(country||'')?country:'unknown';
 image.src='/assets/flags/'+code+'.svg';image.alt='Флаг: '+name;image.loading='lazy';
 image.onerror=()=>{image.onerror=null;image.src='/assets/flags/unknown.svg';};frame.append(image);return frame;
}
async function market(){
 const rev=++state.revision,target=$('categories'),selection=state.country,mode=state.mode;
 $('back-countries').hidden=!selection;$('catalog-title').textContent=selection?'Категории':'Каталог';
 $('catalog-caption').textContent=selection?'Выберите статус аккаунта. Рядом указана цена из актуального наличия.':'Выберите страну, затем категорию аккаунта.';
 target.replaceChildren();for(let i=0;i<4;i++)target.append(el('div',undefined,'skeleton'));
 try{
  const params=new URLSearchParams({mode,q:$('search').value.trim()});if(selection)params.set('country',selection);
  const data=await api('category-market?'+params);if(rev!==state.revision)return;
  target.replaceChildren();$('count').textContent=data.items.length+(selection?' категорий':' стран');
  if(!data.items.length)return empty(target,'В этом разделе пока нет доступных товаров.');
  for(const [index,item] of data.items.entries()){
   const c=el('article',undefined,'category');c.style.setProperty('--delay',Math.min(index,8)*35+'ms');
   const head=el('div',undefined,'category-head');head.append(countryAvatar(item.country,item.name),el('span',item.count+' товаров','stock'));
   const price=el('div',undefined,'category-price');price.append(el('small','от '),document.createTextNode(money(item.min_price)));
   const action=selection?()=>purchase(item,mode):()=>{state.country=item.country;$('search').value='';return market();};
   c.append(head,el('h3',item.name),price,btn(selection?'Купить':'Категории',action,'primary'));target.append(c);
  }
 }catch(e){if(rev===state.revision){target.replaceChildren();empty(target,clean(e.message));}}
}
$('back-countries').onclick=()=>{state.country=null;$('search').value='';market();};
async function purchase(item,mode=state.mode){const quote=await api('category-quote',{mode,nation:item.nation});const body=open('Покупка категории');body.append(el('h3',quote.name),el('p','Один свободный аккаунт будет подобран автоматически.','muted'));const total=el('strong',money(quote.price),'category-price');body.append(total);if(quote.warranty_hours)body.append(el('p','Гарантия: '+quote.warranty_hours+' ч.','muted'));body.append(btn('Купить за '+money(quote.price),async()=>{const result=await api('category-buy',{token:quote.token});await me();await order(result.id);toast('Покупка оформлена');market();},'primary full'));}
async function order(id){
 const data=await api('orders/'+id),body=open('Заказ #'+id);
 body.append(el('p',data.status_label||data.status,'muted'));
 if(data.status==='refunded'){body.append(el('p','Средства возвращены на баланс.'));return;}
 const value='Номер: '+(data.number||'—')+'\nПароль 2FA: '+(data.password||'Не установлен');
 body.append(el('div',value,'order-data'),btn('Скопировать данные',async()=>{await navigator.clipboard.writeText(value);toast('Скопировано');},'subtle full'));
 if(data.status==='issued'){
  body.append(el('p','Введите номер в Telegram и запросите вход. Затем нажмите кнопку ниже.','muted'));
  const result=el('div',undefined,'login-code-result');result.setAttribute('aria-live','polite');
  const fetchCode=btn('Получить код',async()=>{
   fetchCode.textContent='Получаем код…';fetchCode.classList.add('loading');result.replaceChildren();
   try{
    const d=await api('orders/'+id+'/code',{});
    if(d.status==='ready')result.append(el('small','Код входа'),el('strong',d.code,'login-code'),btn('Скопировать код',async()=>{await navigator.clipboard.writeText(d.code);toast('Код скопирован');},'subtle full'));
    else result.append(el('p',d.message||'Код пока не пришёл. Повторите через 10 секунд.','muted'));
   }catch(e){result.append(el('p',clean(e.message),'inline-error'));}
   finally{fetchCode.textContent='Получить код';fetchCode.classList.remove('loading');}
  },'primary full');body.append(fetchCode,result);
 }else body.append(el('p','Получение кода недоступно: рабочая сессия этого заказа завершена.','muted'));
}
async function orders(){const body=open('Мои покупки');let page=0;async function more(){const data=await api('orders?page='+page);if(!page&&!data.items.length)empty(body,'Покупок пока нет.');data.items.forEach(item=>row(body,'Заказ #'+item.id,(item.name||'Аккаунт')+' · '+(item.status_label||item.status),btn('Открыть',()=>order(item.id))));if(data.has_more){const b=btn('Показать ещё',async()=>{b.remove();page++;await more();},'full');body.append(b);}}await more();}
async function profile(){await me();const summary=await api('wallet/summary');$('deposited').textContent=money(summary.deposited);$('spent').textContent=money(summary.spent);$('purchased').textContent=String(summary.purchase_count);}
async function chat(older=false){if(state.tab!=='messages')return;state.chatMessages??=new Map();const first=Math.min(...state.chatMessages.keys());const data=await api('chat'+(older&&Number.isFinite(first)?'?before='+first:''));const latest=data.items.at(-1)?.id||0;if(!state.chatMessages.size||older)state.hasOlder=data.has_more;const changed=older||latest!==state.chatLast||!$('chat-history').childElementCount;data.items.forEach(item=>state.chatMessages.set(item.id,item));if(!older)state.chatLast=latest;if(!changed)return;const box=$('chat-history'),previous=box.scrollHeight;box.replaceChildren();if(!state.chatMessages.size)empty(box,'Напишите нам. Поддержка ответит здесь и в Telegram-боте.');[...state.chatMessages.values()].sort((a,b)=>a.id-b.id).forEach(item=>{const b=el('article',undefined,'bubble'+(item.author_role==='user'?' mine':''));b.append(document.createTextNode(item.body),el('small',(item.author_role==='admin'?'Поддержка':'Вы')+' · '+date(item.created_at)));box.append(b);});$('older-chat').hidden=!state.hasOlder;if(!older&&data.items.length)box.lastElementChild?.scrollIntoView({block:'nearest',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});else if(older)window.scrollBy(0,box.scrollHeight-previous);}
$('older-chat').onclick=()=>chat(true).catch(e=>toast(e.message));
$('chat-form').addEventListener('submit',async event=>{event.preventDefault();const value=$('chat-body').value.trim();if(!value)return;const b=event.currentTarget.querySelector('button');b.disabled=true;try{await api('chat',{body:value});$('chat-body').value='';await chat();}catch(e){toast(e.message);}finally{b.disabled=false;}});
async function topup(){
 const body=open('Пополнить баланс'),content=el('div'),notice=el('p',undefined,'topup-notice');
 notice.setAttribute('role','status');notice.setAttribute('aria-live','polite');body.append(content,notice);
 function note(text,error=true){notice.textContent=clean(text);notice.classList.toggle('inline-error',error);}
 try{
  const methods=(await api('payment-methods')).items;let chosen=methods.find(m=>m.enabled),invoice=null;
  const amount=el('input');amount.type='text';amount.inputMode='decimal';amount.autocomplete='off';amount.value='100';amount.maxLength=24;
  const unit=el('span','Сумма, ₽'),group=el('label',undefined,'form-label');group.append(unit,amount);content.append(group);
  const presets=el('div',undefined,'actions');for(const value of [100,300,500,1000])presets.append(btn(String(value),()=>{amount.value=String(value);resetInvoice();note('');}));content.append(presets);
  content.append(el('p','Способ оплаты','muted'));const choices=el('div',undefined,'payment-choices');choices.setAttribute('role','group');choices.setAttribute('aria-label','Способы оплаты');content.append(choices);
  const info=el('p',undefined,'payment-info');content.append(info);
  const pay=el('button','Перейти к оплате','primary full');pay.type='button';pay.disabled=!chosen;
  const check=el('button','Проверить оплату','full');check.type='button';check.hidden=true;content.append(pay,check);
  function resetInvoice(){invoice=null;check.hidden=true;}
  function busy(value){amount.disabled=value;presets.querySelectorAll('button').forEach(b=>b.disabled=value);choices.querySelectorAll('button').forEach(b=>b.disabled=value||!methods.find(m=>m.id===b.dataset.method)?.enabled);}
  function update(){
   unit.textContent=chosen?.id==='stars'?'Количество Stars':'Сумма, ₽';
   choices.querySelectorAll('button').forEach(b=>{const selected=b.dataset.method===chosen?.id;b.classList.toggle('selected',selected);b.setAttribute('aria-pressed',String(selected));const caption=b.querySelector('small');if(caption)caption.textContent=selected?'Выбрано':methods.find(m=>m.id===b.dataset.method)?.enabled?'Выбрать':'Пока недоступно';});
   info.textContent=chosen?('От '+chosen.min+' до '+chosen.max+(chosen.id==='stars'?' Stars':' ₽')):'Способы оплаты пока не настроены.';
  }
  for(const method of methods){
   const b=el('button',undefined,'payment-method');b.type='button';b.dataset.method=method.id;b.disabled=!method.enabled;
   b.append(el('strong',clean(method.name)),el('small',method.enabled?'Выбрать':'Пока недоступно'));
   b.onclick=()=>{if(pay.disabled&&chosen)return;chosen=method;resetInvoice();note('');update();};choices.append(b);
  }
  amount.addEventListener('input',()=>{resetInvoice();note('');});update();
  pay.addEventListener('click',async()=>{
   note('');const raw=amount.value.trim().replace(',','.');const value=Number(raw);
   if(!chosen?.enabled)return note('Выберите доступный способ оплаты.');
   if(!/^[0-9]+(?:[.][0-9]{1,2})?$/.test(raw)||!Number.isFinite(value)||value<=0)return note('Введите корректное положительное число.');
   if(chosen.id==='stars'&&!Number.isInteger(value))return note('Количество Stars должно быть целым числом.');
   if(value<Number(chosen.min)||value>Number(chosen.max))return note('Допустимое значение: от '+chosen.min+' до '+chosen.max+(chosen.id==='stars'?' Stars.':' ₽.'));
   pay.disabled=true;busy(true);pay.textContent='Создаём счёт…';pay.classList.add('loading');
   try{
    const saved=await api('invoices',chosen.id==='stars'?{provider:'stars',stars:value}:{provider:chosen.id,amount:raw});
    const url=new URL(saved.pay_url);if(url.protocol!=='https:')throw Error('Ссылка оплаты недоступна. Попробуйте позже.');
    if(!content.isConnected)return;invoice=saved;check.hidden=false;note('Счёт создан. После оплаты нажмите «Проверить оплату».',false);
    if(saved.provider==='stars'&&tg?.openInvoice)tg.openInvoice(saved.pay_url,status=>{if(invoice===saved&&status==='paid')check.click();});
    else if(tg?.openLink)tg.openLink(saved.pay_url);else window.open(saved.pay_url,'_blank','noopener');
   }catch(e){note(e.message);}
   finally{busy(false);pay.disabled=false;pay.textContent='Перейти к оплате';pay.classList.remove('loading');}
  });
  check.addEventListener('click',async()=>{
   if(!invoice)return;const selected=invoice;check.disabled=true;note('Проверяем оплату…',false);
   try{
    const result=await api('invoices/'+encodeURIComponent(selected.provider)+'/'+encodeURIComponent(selected.invoice_id)+'/check',{});
    if(invoice!==selected)return;
    if(result.status==='credited'){await me();note('Оплата подтверждена. Баланс пополнен.',false);resetInvoice();}
    else note('Оплата пока не подтверждена. Попробуйте проверить позже.',false);
   }catch(e){note(e.message);}finally{check.disabled=false;}
  });
 }catch(e){note(e.message);}
}
async function transactions(){
 const body=open('История операций');let page=0;
 async function more(){
  const data=await api('wallet/transactions?page='+page);
  if(!page&&!data.items?.length)empty(body,'Операций пока нет.');
  for(const item of data.items||[]){
   const value=item.amount==null?'Не сохранено':item.currency==='RUB'?money(item.amount):String(item.amount)+' '+(item.currency==='PCT'?'%':item.currency||'');
   row(body,item.label||'Операция',date(item.occurred_at),el('strong',value));
  }
  if(data.has_more){const b=btn('Показать ещё',async()=>{b.remove();page++;await more();},'full');body.append(b);}
 }
 await more();
}
async function promo(){const body=open('Ввести промокод');const input=el('input');input.maxLength=40;input.autocomplete='off';label(body,'Промокод',input);body.append(btn('Активировать',async()=>{await api('promo/redeem',{code:input.value.trim()});await me();toast('Промокод активирован');$('modal').close();},'primary full'));}
async function rewards(){const data=await api('rewards');const body=open('Бонусы');body.append(el('p','Бонус доступен по действующим условиям магазина. Пополнения и период получения проверяются автоматически.','muted'));if(data.eligible)body.append(btn('Получить бонус',async()=>{await api('rewards/claim',{});await me();toast('Бонус начислен');$('modal').close();},'primary full'));else body.append(el('p',data.next_at?'Следующее получение: '+date(data.next_at):'Пока нет подходящих пополнений.'));}
async function referrals(){const data=await api('referrals');const body=open('Реферальная система');const link='https://t.me/'+state.me.bot_username+'?start=ref_'+state.me.user.id;body.append(el('p','Приглашайте друзей по своей ссылке. Вознаграждения начисляются по действующим условиям магазина.','muted'),el('div',link,'order-data'),btn('Скопировать ссылку',async()=>{await navigator.clipboard.writeText(link);toast('Ссылка скопирована');},'primary full'));if(data.daily)body.append(el('p','Начислено сегодня: '+money(data.daily.issued)+' · Лимит: '+money(data.daily.limit),'muted'));}
function information(){const body=open('Информация');body.append(el('p','По вопросам покупки обратитесь в раздел «Сообщения».','muted'));for(const [title,url] of [['Пользовательское соглашение','https://telegra.ph/POLZOVATELSKOE-SOGLASHENIE-SBAND-ACCS-11-05'],['Политика конфиденциальности','https://telegra.ph/POLITIKA-KONFIDENCIALNOSTI-SBAND-ACCS-11-05-2']]){const a=el('a',title);a.href=url;a.target='_blank';a.rel='noopener noreferrer';const p=el('p');p.append(a);body.append(p);}}
const actions={orders,transactions,promo,rewards,referrals,information};
document.querySelectorAll('[data-action]').forEach(b=>b.addEventListener('click',()=>Promise.resolve().then(()=>actions[b.dataset.action]()).catch(e=>toast(e.message))));
async function navigate(tab){state.tab=tab;document.querySelectorAll('.page').forEach(p=>p.hidden=p.id!==tab);document.querySelectorAll('[data-tab]').forEach(b=>{b.classList.toggle('selected',b.dataset.tab===tab);if(b.dataset.tab===tab)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});const p=$(tab);p.classList.remove('page');void p.offsetWidth;p.classList.add('page');try{if(tab==='market')await market();else if(tab==='profile')await profile();else await chat();}catch(e){toast(e.message);}}
document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>navigate(b.dataset.tab)));
document.querySelectorAll('[data-mode]').forEach(b=>b.addEventListener('click',()=>{state.mode=b.dataset.mode;state.country=null;document.querySelectorAll('[data-mode]').forEach(other=>other.classList.toggle('selected',other===b));market();}));
$('search').addEventListener('input',()=>{clearTimeout(state.searchTimer);state.searchTimer=setTimeout(market,220);});
$('close-modal').onclick=()=>$('modal').close();$('wallet').onclick=()=>topup().catch(e=>toast(e.message));$('topup').onclick=$('wallet').onclick;
$('admin-link').onclick=()=>location.assign('/admin-app');
document.querySelector('.brand').addEventListener('click',event=>{event.preventDefault();navigate('market');});
document.addEventListener('pointerdown',event=>{const b=event.target.closest('button');if(!b||b.disabled||matchMedia('(prefers-reduced-motion: reduce)').matches)return;b.animate([{transform:'scale(1)',filter:'brightness(1)'},{transform:'scale(.95)',filter:'brightness(1.25)'},{transform:'scale(1)',filter:'brightness(1)'}],{duration:260,easing:'cubic-bezier(.2,.8,.2,1)'});});
const polling=setInterval(()=>{if(state.tab==='messages'&&!document.hidden)chat().catch(()=>{});},6000);window.addEventListener('beforeunload',()=>clearInterval(polling));
(async()=>{try{tg?.ready();tg?.expand();tg?.setHeaderColor('#08090c');tg?.setBackgroundColor('#08090c');await me();await market();}catch(e){$('categories').replaceChildren();empty($('categories'),clean(e.message));}})();
