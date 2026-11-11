'use strict';
const tg = window.Telegram?.WebApp;
const $ = id => document.getElementById(id);
const content = $('content');
const statusNames = {available:'В наличии',review:'На проверке',sold:'Продан',issued:'Выдан',completed:'Завершён',refunded:'Возвращён',pending:'Ожидает оплаты',credited:'Зачислен',expired:'Истёк',replaced:'Заменён'};
let page = 'overview', offset = 0, query = '', generation = 0, save = null, saving = false;
const rub = value => new Intl.NumberFormat('ru-RU',{style:'currency',currency:'RUB'}).format(Number(value || 0));
function node(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = String(text);
  if (className) item.className = className;
  return item;
}
function button(text, action, primary = false) {
  const b = node('button', text, primary ? 'primary' : ''); b.type = 'button';
  b.addEventListener('click', () => Promise.resolve(action()).catch(showError));
  return b;
}
function showError(error) { $('notice').textContent = error.message || 'Не удалось выполнить запрос.'; }
async function api(path, method = 'GET', body) {
  const response = await fetch('/api/admin/' + path, {
    method, credentials:'omit', cache:'no-store',
    headers:{Authorization:'tma ' + (tg?.initData || ''), ...(body ? {'Content-Type':'application/json'} : {})},
    body:body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json();
  if (!response.ok) throw Error(data.error || 'Запрос недоступен.');
  return data;
}
function row(parent, title, detail, trailing, action) {
  const line = node('div', undefined, 'row'); const info = node('div',undefined,'detail');
  info.append(node('strong',title),node('span',detail,'muted')); line.append(info);
  if (trailing) line.append(node('span',trailing));
  if (action) { const actions = node('div',undefined,'actions'); actions.append(...action); line.append(actions); }
  parent.append(line);
}
function form(title, fields, submit) {
  $('edit-title').textContent = title; $('fields').replaceChildren(); $('form-error').textContent = '';
  const controls = {};
  for (const [key,label,value,type = 'text',options] of fields) {
    const wrapper = node('label',label); let input;
    if (options) {
      input = node('select');
      for (const [v,text] of options) { const option = node('option',text); option.value = v; input.append(option); }
    } else { input = node(type === 'textarea' ? 'textarea' : 'input'); if (type !== 'textarea') input.type = type; }
    input.value = value ?? ''; input.required = type !== 'textarea'; controls[key] = input;
    if (type === 'number') input.step = key === 'limit' || key === 'warranty_hours' ? '1' : '0.01';
    wrapper.append(input); $('fields').append(wrapper);
  }
  save = () => submit(Object.fromEntries(Object.entries(controls).map(([k,v]) => [k,v.value])));
  $('editor').showModal();
}
$('cancel').addEventListener('click', () => { if (!saving) $('editor').close(); });
$('editor').addEventListener('cancel', event => { if (saving) event.preventDefault(); });
$('edit-form').addEventListener('submit', async event => {
  event.preventDefault(); if (saving || !save) return;
  saving = true; const buttons = [...$('edit-form').querySelectorAll('button')]; buttons.forEach(b => b.disabled = true);
  try { await save(); $('editor').close(); await load(); }
  catch (error) { $('form-error').textContent = error.message; }
  finally { saving = false; buttons.forEach(b => b.disabled = false); }
});
function stockEditor(item) {
  form('Товар #' + item.id, [
    ['price','Цена, ₽',item.price,'number'], ['category','Код категории',item.country],
    ['warranty_hours','Гарантия, часов',item.warranty_hours || 0,'number'],
    ['note','Примечание',item.features_note || '','textarea'],
  ], values => api('stock/' + item.id,'PATCH',{
    ...values,warranty_hours:Number(values.warranty_hours),
    registration_date:item.registration_date,is_premium:item.is_premium == null ? null : Boolean(item.is_premium),
  }));
}
function categoryEditor(item = {}) {
  form('Категория', [['slug','Код',item.slug || ''],['name','Название',item.name || ''],
    ['active','Доступность',item.is_active === 0 ? '0' : '1','text',[['1','Включена'],['0','Отключена']]]],
    values => api('categories','POST',{slug:values.slug,name:values.name,active:values.active === '1'}));
}
function balanceEditor(user) {
  // A failed request reuses this key; never create a new operation on retry.
  const operationId = crypto.randomUUID().replaceAll('-','');
  form('Баланс пользователя ' + user.id, [
    ['amount','Сумма', '','number'],['currency','Валюта','RUB','text',[['RUB','Рубли'],['USDT','USDT']]],
    ['mode','Действие','add','text',[['add','Добавить к балансу'],['set','Установить баланс']]],
  ], values => api('users/' + user.id + '/balance','POST',{...values,operation_id:operationId}));
}
function promoEditor() {
  form('Новый промокод', [['code','Код',''],
    ['kind','Тип','discount','text',[['discount','Скидка, %'],['balance','Бонус на баланс, ₽']]],
    ['percent','Размер скидки или бонуса','','number'],['limit','Лимит использований',1,'number']],
    values => api('promos','POST',{...values,percent:Number(values.percent),limit:Number(values.limit)}));
}
async function load() {
  const current = ++generation; const selected = page;
  content.setAttribute('aria-busy','true'); $('notice').textContent = '';
  try {
    const params = new URLSearchParams({page:String(offset),q:query});
    const result = await api(selected + (['stock','orders','users','payments'].includes(selected) ? '?' + params : ''));
    if (current !== generation) return;
    content.replaceChildren();
    const titles = {overview:'Обзор',stock:'Товары',users:'Пользователи',orders:'Заказы',categories:'Категории',promos:'Промокоды',payments:'История платежей'};
    content.append(node('h2',titles[selected]));
    if (['stock','orders','users','payments'].includes(selected)) {
      const search = node('form',undefined,'tools'); const input = node('input');
      input.type='search'; input.value=query; input.placeholder=selected === 'users' ? 'ID или имя пользователя' : 'Поиск'; input.setAttribute('aria-label','Поиск');
      const submit = node('button','Найти'); submit.type='submit'; search.append(input,submit);
      search.addEventListener('submit',event => {event.preventDefault();query=input.value.trim();offset=0;load();}); content.append(search);
    }
    if (selected === 'overview') {
      const stats = node('div',undefined,'stats');
      for (const [key,label] of [['stock','Товаров в наличии'],['orders','Заказов'],['users','Пользователей'],['approvals','Возвратов на согласовании']]) {
        const card=node('div',undefined,'card');card.append(node('span',label,'muted'),node('strong',result[key] ?? 0));stats.append(card);
      }
      content.append(stats);
      const info=node('div',undefined,'card');info.append(node('h2','Поддержка напрямую'),node('p','Сообщения приходят администраторам в бота. Чтобы ответить, нажмите кнопку под сообщением пользователя.'));content.append(info);
      return;
    }
    if (selected === 'categories') content.append(button('Добавить категорию', () => categoryEditor(), true));
    if (selected === 'promos') content.append(button('Создать промокод',promoEditor,true));
    const list=node('div',undefined,'card');content.append(list);
    if (selected === 'users') {
      const user=result.user;
      if (!user) list.append(node('p','Пользователь не найден. Укажите ID или имя.','muted'));
      else row(list,'@' + (user.username || user.id),'ID: ' + user.id + ' · ' + (user.balance_usdt ?? 0) + ' USDT',rub(user.balance),[button('Изменить баланс', () => balanceEditor(user))]);
    } else {
      const items=result.items || [];
      if (!items.length) list.append(node('p','Записей пока нет.','muted'));
      for (const item of items) {
        if (selected === 'stock') row(list,(item.name || item.country) + ' · #' + item.id,item.number + ' · ' + (statusNames[item.status] || item.status),rub(item.price),['available','review'].includes(item.status) ? [button('Изменить', () => stockEditor(item))] : []);
        if (selected === 'orders') row(list,'Заказ #' + item.id,(item.name || 'Товар') + ' · ID покупателя: ' + item.user_id + ' · ' + (statusNames[item.status] || item.status),item.currency === 'RUB' ? rub(item.paid_amount) : (item.paid_amount ?? '—') + ' ' + item.currency);
        if (selected === 'categories') row(list,item.name,item.slug,item.is_active ? 'Включена' : 'Отключена',[button('Изменить', () => categoryEditor(item))]);
        if (selected === 'promos') row(list,item.code,'Использовано: ' + item.uses + ' из ' + item.max_uses,item.kind === 'discount' ? item.value + '%' : rub(item.value));
        if (selected === 'payments') row(list,item.provider + ' · ' + item.invoice_id,'ID: ' + item.user_id + ' · ' + (statusNames[item.status] || item.status) + ' · ' + item.created_at,rub(item.amount_rub));
      }
    }
    if (['stock','orders','payments'].includes(selected) && (offset || result.has_more)) {
      const pager=node('div',undefined,'pagination'); const prev=button('Назад',()=>{offset--;return load();});prev.disabled=!offset;
      const next=button('Далее',()=>{offset++;return load();});next.disabled=!result.has_more;pager.append(prev,node('span','Страница ' + (offset+1)),next);content.append(pager);
    }
  } catch(error) {if (current === generation) showError(error);}
  finally {if (current === generation) content.removeAttribute('aria-busy');}
}
document.querySelectorAll('[data-page]').forEach(b => b.addEventListener('click',()=>{
  page=b.dataset.page;offset=0;query='';
  document.querySelectorAll('[data-page]').forEach(other => other.removeAttribute('aria-current'));b.setAttribute('aria-current','page');load();
}));
(async () => {
  try {
    tg?.ready();tg?.expand();
    if (!tg?.initData) throw Error('Откройте администраторское приложение из Telegram.');
    const identity=await api('identity');
    if (!identity.is_admin) throw Error('Доступ только администратору.');
    $('identity').textContent=identity.user.username ? '@' + identity.user.username : String(identity.user.id);
    $('access').hidden=true;$('app').hidden=false;await load();
  } catch(error) {$('access').textContent=error.message;}
})();
