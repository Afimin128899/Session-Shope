'use strict';
const tg = window.Telegram?.WebApp;
const $ = id => document.getElementById(id);
const content = $('content');
const statusNames = {available:'В наличии',review:'На проверке',sold:'Продан',issued:'Выдан',completed:'Завершён',refunded:'Возвращён',pending:'Ожидает оплаты',credited:'Зачислен',expired:'Истёк',replaced:'Заменён'};
let stockTimer=null,stockStatus='available';
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
  if(/^Удалить/.test(text))b.classList.add('danger');
  b.addEventListener('click', () => SbandUI.run(b,action).catch(showError));
  return b;
}
function showError(error) { $('notice').classList.add('ui-status-error');$('notice').textContent = error.message || 'Не удалось выполнить запрос.'; }
async function api(path, method = 'GET', body) {
  const {response,data} = await SbandUI.request('/api/admin/' + path, {
    method, credentials:'omit', cache:'no-store',
    headers:{Authorization:'tma ' + (tg?.initData || ''), ...(body ? {'Content-Type':'application/json'} : {})},
    body:body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw Error(data.error || 'Запрос недоступен.');
  return data;
}
function row(parent, title, detail, trailing, action) {
  const line = node('div', undefined, 'row'); const info = node('div',undefined,'detail');
  info.append(node('strong',title),node('span',detail,'muted')); line.append(info);
  if (trailing) line.append(node('span',trailing,'row-value'));
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
    input.value = value ?? ''; input.required = type !== 'textarea' && key !== 'registration_date'; controls[key] = input;
    if (type === 'number') input.step = key === 'limit' || key === 'warranty_hours' ? '1' : '0.01';
    wrapper.append(input); $('fields').append(wrapper);
  }
  save = () => submit(Object.fromEntries(Object.entries(controls).map(([k,v]) => [k,v.value])));
  $('editor').dataset.intent=title.startsWith('Удалить')?'danger':'normal';
  $('edit-form').querySelector('button[type=submit]').classList.toggle('danger',title.startsWith('Удалить'));
  $('edit-form').querySelector('button[type=submit]').classList.toggle('primary',!title.startsWith('Удалить'));
  $('edit-form').querySelector('button[type=submit]').textContent=title.startsWith('Удалить')?'Удалить выбранные':'Сохранить';
  SbandUI.open($('editor'));
}
$('cancel').addEventListener('click', () => { if (!saving) SbandUI.close($('editor')); });
$('editor').addEventListener('cancel', event => {event.preventDefault();if(!saving)SbandUI.close($('editor'));});
$('edit-form').addEventListener('submit', async event => {
  event.preventDefault(); if (saving || !save) return;
  saving = true;$('edit-form').querySelector('button[type=submit]').classList.add('is-busy');$('edit-form').querySelector('button[type=submit]').setAttribute('aria-busy','true'); const buttons = [...$('edit-form').querySelectorAll('button')]; buttons.forEach(b => b.disabled = true);
  try { await save(); $('editor').close(); await load(); if(categoryPriceResult){$('notice').textContent=categoryPriceResult;categoryPriceResult='';} }
  catch (error) { $('form-error').textContent = error.message; }
  finally { saving = false; buttons.forEach(b => b.disabled = false);$('edit-form').querySelector('button[type=submit]').classList.remove('is-busy');$('edit-form').querySelector('button[type=submit]').removeAttribute('aria-busy'); }
});
function stockEditor(item) {
  form('Товар #' + item.id, [
    ['price','Цена, ₽',item.price,'number'], ['category','Код категории',item.country],
    ['registration_date','Дата регистрации (из JSON)',item.registration_date||'','date'],
    ['warranty_hours','Гарантия, часов',item.warranty_hours || 0,'number'],
    ['note','Примечание',item.features_note || '','textarea'],
  ], values => api('stock/' + item.id,'PATCH',{
    ...values,warranty_hours:Number(values.warranty_hours),
    registration_date:values.registration_date||null,is_premium:item.is_premium == null ? null : Boolean(item.is_premium),
  }));
}
function categoryEditor(item = {}) {
  form('Категория', [['slug','Код',item.slug || ''],['name','Название',item.name || ''],
    ['active','Доступность',item.is_active === 0 ? '0' : '1','text',[['1','Включена'],['0','Отключена']]]],
    values => api('categories','POST',{slug:values.slug,name:values.name,active:values.active === '1'}));
}
function categoryPriceEditor(item) {
  form('Цена товаров: ' + item.name, [
    ['price','Новая цена всех непроданных товаров категории, ₽','','number'],
  ], async values => {
    const result = await api('categories/price','POST',{slug:item.slug,price:values.price});
    // load() clears the page notice, so show the result after the dialog reload.
    categoryPriceResult = 'Цена обновлена. Изменено товаров: ' + result.updated;
  });
}
let categoryPriceResult = '';
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
function sessionJobEditor(action) {
  const reauthorize=action==='reauthorize';
  form(reauthorize?'Новая авторизация всех непроданных аккаунтов':'Отправить все сессии и JSON в личный чат',[
    ['confirm',reauthorize?'Введите ПЕРЕСОЗДАТЬ. Сессия заменится только после успешного входа.':'Введите ОТПРАВИТЬ. ZIP содержит данные входа.',''],
  ],async values=>{
    if(values.confirm.trim()!==(reauthorize?'ПЕРЕСОЗДАТЬ':'ОТПРАВИТЬ'))throw Error('Введите слово подтверждения.');
    await api('session-jobs','POST',{action});
    categoryPriceResult='Операция запущена. ZIP и отчёты придут в ваш личный чат с ботом.';
  });
}
const selectedStock = new Set();
let bulkBusy = false;
function stockSelectionTools(items) {
  const tools=node('div',undefined,'tools stock-selection');
  const count=node('span');
  const refresh=()=>{count.textContent='Выбрано: '+selectedStock.size;tools.dataset.selected=String(selectedStock.size>0);tools.querySelectorAll('.selection-actions button').forEach(b=>{if(!b.hasAttribute('aria-busy'))b.disabled=!selectedStock.size;});content.querySelectorAll('[data-stock-id]').forEach(box=>box.closest('.row')?.classList.toggle('is-selected',box.checked));checkbox.checked=available.length>0&&available.every(item=>selectedStock.has(item.id));checkbox.indeterminate=available.some(item=>selectedStock.has(item.id))&&!checkbox.checked;};
  const all=node('label',undefined,'stock-select');
  const checkbox=node('input');checkbox.type='checkbox';
  const available=items.filter(item=>item.status==='available');
  checkbox.checked=available.length>0&&available.every(item=>selectedStock.has(item.id));
  checkbox.addEventListener('change',()=>{
    if(checkbox.checked&&new Set([...selectedStock,...available.map(item=>item.id)]).size>100){checkbox.checked=false;showError(Error('Можно выбрать до 100 товаров.'));return;}
    for(const item of available) checkbox.checked?selectedStock.add(item.id):selectedStock.delete(item.id);
    content.querySelectorAll('[data-stock-id]').forEach(box=>{box.checked=selectedStock.has(Number(box.dataset.stockId));});refresh();
  });
  all.append(checkbox,node('span','Все на странице'));tools.append(all,count);
  async function execute(action,ids,value) {
    if(bulkBusy)throw Error('Дождитесь завершения операции.');
    bulkBusy=true;let completed=0,queued=0;
    const progress=node('div',undefined,'batch-progress'),caption=node('span','Обработано: 0 из '+ids.length),bar=node('progress',undefined,'loading-progress');bar.max=ids.length;bar.value=0;bar.setAttribute('aria-label','Обработано выбранных товаров');progress.append(caption,bar);if($('editor').open)$('edit-form').insertBefore(progress,$('edit-form').querySelector('footer'));else tools.append(progress);
    const advance=()=>{bar.value=completed;caption.textContent='Обработано: '+completed+' из '+ids.length;};
    try{
      if(action==='price'){
        await api('stock/bulk','POST',{ids,field:'price',value});completed=ids.length;advance();
        ids.forEach(id=>selectedStock.delete(id));
      }else for(const id of ids){
        const result=action==='delete'?await api('stock/'+id,'DELETE'):await api('stock/'+id+'/spam-check','POST',{});
        queued+=result.queued||0;completed++;advance();selectedStock.delete(id);
      }
      const message=action==='spam'?'Поставлено в очередь: '+queued+' из '+ids.length+'. Остальные могут уже проверяться или ожидать повторного запроса.':'Обработано товаров: '+completed;
      if(action==='spam'){await load();$('notice').textContent=message;}else{categoryPriceResult=message;}
    }catch(error){await load();throw Error('Обработано: '+completed+' из '+ids.length+'. '+error.message);}
    finally{bulkBusy=false;progress.remove();}
  }
  function choose(action){
    if(bulkBusy)throw Error('Дождитесь завершения операции.');
    const ids=[...selectedStock];if(!ids.length)throw Error('Отметьте товары галочками.');
    if(action==='price')form('Цена выбранных товаров: '+ids.length,[['price','Новая цена, ₽','','number']],v=>execute(action,ids,v.price));
    else if(action==='delete')form('Удалить выбранные товары: '+ids.length,[['confirm','Для удаления введите УДАЛИТЬ','']],v=>{
      if(v.confirm.trim()!=='УДАЛИТЬ')throw Error('Введите УДАЛИТЬ для подтверждения.');
      return execute(action,ids);
    });
    else return execute(action,ids);
  }
  const selectionActions=node('div',undefined,'selection-actions');selectionActions.append(button('Изменить цену',()=>choose('price')),button('Проверить спамблок',()=>choose('spam')),button('Удалить выбранные',()=>choose('delete')),button('Снять выделение',()=>{selectedStock.clear();return load();}));tools.append(selectionActions);
  refresh();content.append(tools);return refresh;
}
async function load() {
  clearTimeout(stockTimer);
  const current = ++generation; const selected = page;
  content.setAttribute('aria-busy','true'); $('notice').classList.remove('ui-status-error');$('notice').textContent = '';
  try {
    const params = new URLSearchParams({page:String(offset),q:query});if(selected==='stock')params.set('status',stockStatus);
    const result = await api(selected + (['stock','orders','users','payments'].includes(selected) ? '?' + params : ''));
    if (current !== generation) return;
    const changed=content.dataset.page!==selected;content.dataset.page=selected;if(changed)SbandUI.enter(content);content.replaceChildren();
    const titles = {overview:'Обзор',stock:'Товары',users:'Пользователи',orders:'Заказы',categories:'Категории',promos:'Промокоды',payments:'История платежей'};
    content.append(node('h2',titles[selected]));
    if (['stock','orders','users','payments'].includes(selected)) {
      const search = node('form',undefined,'tools'); const input = node('input');
      input.type='search'; input.value=query; input.placeholder=selected === 'users' ? 'ID или имя пользователя' : 'Поиск'; input.setAttribute('aria-label','Поиск');
      const submit = node('button','Найти'); submit.type='submit'; search.append(input);
      if(selected==='stock'){const status=node('select');status.setAttribute('aria-label','Статус товара');for(const [value,title] of [['available','В наличии'],['review','На проверке'],['sold','Проданы'],['','Все статусы']]){const option=node('option',title);option.value=value;status.append(option);}status.value=stockStatus;status.addEventListener('change',()=>{stockStatus=status.value;query=input.value.trim();offset=0;load();});search.append(status);}search.append(submit);
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
    let refreshSelection;
    if (selected === 'stock') {
      const toolbar=node('div',undefined,'stock-toolbar');toolbar.append(button('Загрузить аккаунты',()=>{page='imports';document.querySelectorAll('[data-page]').forEach(b=>b.dataset.page==='imports'?b.setAttribute('aria-current','page'):b.removeAttribute('aria-current'));return load();},true));
      const details=node('details'),summary=node('summary','Операции с сессиями'),actions=node('div',undefined,'detail-actions');
      actions.append(button('Проверить на спамблок все',()=>queueSpam()),button('Все сессии и JSON в чат',()=>sessionJobEditor('export')),button('Пересоздать все сессии',()=>sessionJobEditor('reauthorize')));details.append(summary,actions);toolbar.append(details);content.append(toolbar);refreshSelection=stockSelectionTools(result.items||[]);
    }
    if (selected === 'categories') content.append(button('Добавить категорию', () => categoryEditor(), true));
    if (selected === 'promos') content.append(button('Создать промокод',promoEditor,true));
    const list=node('div',undefined,'card');if(selected==='stock'){list.classList.add('stock-table');const heading=node('div',undefined,'stock-table-heading');heading.setAttribute('aria-hidden','true');for(const text of ['','Товар и сведения','Цена','Действия'])heading.append(node('span',text));list.append(heading);}content.append(list);
    if (selected === 'users') {
      const user=result.user;
      if (!user) list.append(node('p','Пользователь не найден. Укажите ID или имя.','muted'));
      else row(list,'@' + (user.username || user.id),'ID: ' + user.id + ' · ' + (user.balance_usdt ?? 0) + ' USDT',rub(user.balance),[button('Изменить баланс', () => balanceEditor(user))]);
    } else {
      const items=result.items || [];
      if (!items.length) list.append(node('p','Записей пока нет.','muted'));
      for (const item of items) {
        if (selected === 'stock') {
          const check=item.spam_check||{};const actions=['available','review'].includes(item.status)?[button('Изменить',()=>stockEditor(item))]:[];
          if(item.status==='available'){
            const b=button(check.running?'Проверяется…':check.queued?'В очереди':'Проверить на спамблок',()=>queueSpam(item.id));
            b.disabled=Boolean(check.running||check.queued);actions.push(b);
          }
          row(list,(item.name||item.country)+' · #'+item.id,item.number+' · '+(statusNames[item.status]||item.status)+' · '+(check.label||'Не проверен')+(check.detail?' · '+check.detail:'')+' · Год регистрации: '+(item.registration_date?String(item.registration_date).slice(0,4):'не указан')+' · Дата: '+(item.registration_date||'не указана'),rub(item.price),actions);
          list.lastElementChild.classList.add('stock-row');
          {
            const label=node('label',undefined,'stock-select');const box=node('input');box.type='checkbox';box.disabled=item.status!=='available';box.dataset.stockId=item.id;box.checked=selectedStock.has(item.id);box.setAttribute('aria-label','Выбрать товар #'+item.id);
            box.addEventListener('change',()=>{
              if(box.checked&&selectedStock.size>=100){box.checked=false;showError(Error('Можно выбрать до 100 товаров.'));return;}
              box.checked?selectedStock.add(item.id):selectedStock.delete(item.id);refreshSelection();
            });label.append(box);list.lastElementChild.prepend(label);
          }
        }
        if (selected === 'orders') row(list,'Заказ #' + item.id,(item.name || 'Товар') + ' · ID покупателя: ' + item.user_id + ' · ' + (statusNames[item.status] || item.status),item.currency === 'RUB' ? rub(item.paid_amount) : (item.paid_amount ?? '—') + ' ' + item.currency);
        if (selected === 'categories') row(list,item.name,item.slug,item.is_active ? 'Включена' : 'Отключена',[button('Цена всех товаров', () => categoryPriceEditor(item)),button('Изменить', () => categoryEditor(item))]);
        if (selected === 'promos') row(list,item.code,'Использовано: ' + item.uses + ' из ' + item.max_uses,item.kind === 'discount' ? item.value + '%' : rub(item.value));
        if (selected === 'payments') row(list,item.provider + ' · ' + item.invoice_id,'ID: ' + item.user_id + ' · ' + (statusNames[item.status] || item.status) + ' · ' + item.created_at,rub(item.amount_rub));
      }
    }
    if(selected==='stock'){refreshSelection();if((result.items||[]).some(item=>item.spam_check?.running||item.spam_check?.queued)){const poll=()=>{if(page!=='stock')return;if($('editor').open||bulkBusy)stockTimer=setTimeout(poll,5000);else load();};stockTimer=setTimeout(poll,5000);}}
    if (['stock','orders','payments'].includes(selected) && (offset || result.has_more)) {
      const pager=node('div',undefined,'pagination'); const prev=button('Назад',()=>{offset--;return load();});prev.disabled=!offset;
      const next=button('Далее',()=>{offset++;return load();});next.disabled=!result.has_more;pager.append(prev,node('span','Страница ' + (offset+1)),next);content.append(pager);
    }
  } catch(error) {if (current === generation){showError(error);content.replaceChildren();SbandUI.errorBox(content,error.message,()=>load());}}
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

async function queueSpam(id){
 const result=await api(id?'stock/'+id+'/spam-check':'spam-checks','POST',{});
 await load();$('notice').textContent=result.queued?'Поставлено в очередь: '+result.queued+'. Результат обновится автоматически.':'Повтор пока недоступен: проверка уже идёт, не прошло 5 минут или действует ограничение Telegram.';
}
