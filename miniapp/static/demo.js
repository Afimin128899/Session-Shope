'use strict';
(() => {
 const $=id=>document.getElementById(id),tg=window.Telegram?.WebApp;
 const raw=tg?.initData||sessionStorage.getItem('sband_test_init')||'';
 const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const rub=value=>new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2}).format(Number(value))+' ₽';
 let state=null,busy=false;
 async function api(path,body){
  if(!raw)throw Error(SbandT("Откройте тестовый магазин через Telegram-бота."));
  const response=await fetch('/api/demo/'+path,{method:body?'POST':'GET',headers:{Authorization:'tma '+raw,...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined,cache:'no-store',signal:AbortSignal.timeout(15000)});
  let data;try{data=await response.json();}catch(_){throw Error(SbandT("Нет полного ответа учебного сервера. Обновите страницу."));}
  if(!response.ok)throw Error(data.error||SbandT("Учебный режим недоступен."));return data;
 }
 function notice(text){$('notice').textContent=text;}
 function total(){
  if(!state)return;
  const items=state.products.filter(p=>state.cart.includes(p.id));
  const promo=$('promo').value.trim().toUpperCase(),valid=!promo||promo==='DEMO10';
  const sum=items.reduce((n,p)=>n+Math.round(Number(p.price)*100)*(promo==='DEMO10'?90:100)/100,0)/100;
  $('total').textContent=valid?SbandT("Учебная сумма к оплате: ")+rub(sum):SbandT("Учебный промокод: DEMO10");
  $('checkout').disabled=!items.length||!valid||busy;
 }
 function render(){
  $('balance').textContent=rub(state.balance);
  $('products').innerHTML=state.products.map(p=>`<article class="training-product"><h3>${esc(p.name)}</h3><p>DEMO-${p.id} · ${rub(p.price)}</p><p>${p.available?SbandT("Учебный товар доступен"):SbandT("Учебный товар выдан")}</p><button class="secondary-button" data-add="${p.id}" ${!p.available||state.cart.includes(p.id)?'disabled':''}>${state.cart.includes(p.id)?SbandT("В учебной корзине"):SbandT("В учебную корзину")}</button></article>`).join('');
  const items=state.products.filter(p=>state.cart.includes(p.id));
  $('cart-summary').textContent=items.length?items.map(p=>p.name+' · '+rub(p.price)).join('; '):SbandT("Учебная корзина пуста");
  $('invoices').innerHTML=state.invoices.map(i=>`<div class="training-row"><span>${esc(i.provider)} · ${rub(i.amount)} · ${i.paid?SbandT("Учебная оплата учтена"):SbandT("Ожидает учебного подтверждения")}</span>${!i.paid?SbandT("<button class=\"secondary-button\" data-pay=\"{0}\">Подтвердить учебную оплату</button>",esc(i.id)):''}</div>`).join('');
  const labels={issued:SbandT("Учебный заказ выдан"),completed:SbandT("Учебный заказ завершён"),refunded:SbandT("Учебный возврат выполнен")};
  $('orders').innerHTML=state.orders.map(o=>SbandT("<div class=\"training-row\"><span><b>DEMO-заказ #{0}</b><br>{1} · {2}<br>{3}</span>{4}{5}</div>",o.id,esc(o.name),rub(o.paid),labels[o.status]||SbandT("Учебный заказ"),o.status==='issued'?SbandT("<button class=\"secondary-button\" data-code=\"{0}\">Учебный код</button><button class=\"secondary-button\" data-complete=\"{1}\">Завершить</button>",o.id,o.id):'',o.status!=='refunded'?SbandT("<button class=\"secondary-button\" data-refund=\"{0}\">Учебный возврат</button>",o.id):'')).join('')||SbandT("<p>Учебных заказов пока нет.</p>");
  $('events').innerHTML=state.events.map(item=>`<li>${esc(item)}</li>`).join('');
  $('reward').disabled=!state.reward_available;total();
 }
 async function action(body){
  if(!state||busy)return;busy=true;total();
  try{state=await api('action',{...body,generation:state.generation});render();notice(state.events.at(-1)||SbandT("Учебный сценарий готов."));}
  catch(e){notice(e.message||SbandT("Учебный сервер недоступен."));}
  finally{busy=false;total();}
 }
 $('provider').onchange=()=>{
  const stars=$('provider').value==='stars';$('amount-label').firstChild.textContent=stars?SbandT("Количество учебных звёзд (1 ⭐ = 1,20 ₽)"):SbandT("Сумма, ₽");
  $('amount').min=stars?'1':'10';$('amount').max=stars?'8333':'10000';$('amount').step=stars?'1':'0.01';$('amount').value='100';
 };
 $('payment').onsubmit=event=>{event.preventDefault();const provider=$('provider').value;action(provider==='stars'?{action:'invoice',provider,stars:Number($('amount').value)}:{action:'invoice',provider,amount:$('amount').value});};
 $('promo').oninput=total;
 $('checkout').onclick=()=>action({action:'checkout',promo:$('promo').value});
 $('reward').onclick=()=>action({action:'reward'});
 $('reset').onclick=()=>{if(confirm(SbandT("Сбросить только ваши учебные покупки и баланс?")))action({action:'reset'});};
 $('exit').onclick=async()=>{if(busy)return;try{await api('exit',{});sessionStorage.removeItem('sband_test_init');location.assign('/'+location.hash);}catch(e){notice(e.message);}};
 document.addEventListener('click',event=>{const button=event.target.closest('button');if(!button||button.disabled)return;
  if(button.dataset.add)action({action:'add',id:Number(button.dataset.add)});
  if(button.dataset.pay)action({action:'pay',invoice_id:button.dataset.pay});
  for(const kind of ['code','complete','refund'])if(button.dataset[kind])action({action:kind,id:Number(button.dataset[kind])});
 });
 (async()=>{try{await window.SbandI18n.ready;tg?.ready();tg?.expand();state=await api('state');render();notice(SbandT("Учебный сценарий готов. Начальный виртуальный баланс — 1 000 ₽. Промокод: DEMO10."));}catch(e){notice(e.message);document.querySelectorAll('button,input,select').forEach(el=>el.disabled=true);}})();
})();
