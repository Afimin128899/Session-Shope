/* Categorized control center over the existing role-checked admin endpoints. */
(()=>{
 'use strict';
 const previousLoad=load;
 const ownPages=new Set(['system-settings','system-audit','user-bans']);
 const labels={order_access_revoked:'Доступ к заказу отозван',order_telegram_sessions:'Завершение сеансов Telegram',web_settings:'Изменение настроек',global_ban:'Блокировка пользователя',global_unban:'Разблокировка пользователя'};
 function go(target){page=target;offset=0;query='';document.querySelectorAll('nav [data-page]').forEach(b=>{if(b.dataset.page===target)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});return load();}
 function positive(value){if(!/^\d+$/.test(value)||!Number.isSafeInteger(Number(value))||Number(value)<=0)throw Error('Укажите корректный ID.');return Number(value);}
 function inspect(title,copy,rows=[]){form(title,[],async()=>{});const submit=$('edit-form').querySelector('[type=submit]');submit.textContent='Готово';$('fields').append(node('p',copy,'muted'));for(const [label,value] of rows)row($('fields'),label,String(value));}
 async function publicApi(path){const {response,data}=await SbandUI.request('/api/'+path,{headers:{Authorization:'tma '+(tg?.initData||'')},cache:'no-store'});if(!response.ok)throw Error(data.error||'Сервис недоступен.');return data;}
 async function gateways(){
  const data=await publicApi('payment-methods');inspect('Платёжные шлюзы и кошельки','Показаны реальные способы оплаты. Ключи задаются в окружении сервера и не передаются в браузер.',data.items.map(m=>[m.name,(m.enabled?'Подключён':'Отключён')+' · '+m.min+'–'+m.max+(m.id==='stars'?' Stars':' ₽')]));
  $('fields').append(node('p','Crypto Pay: CRYPTO_PAY_TOKEN · Heleket: HELEKET_MERCHANT_ID / HELEKET_PAYMENT_KEY · СБП: PLATEGA_MERCHANT_ID / PLATEGA_SECRET. После изменения окружения перезапустите сервис.','terminal-code'));
 }
 async function maintenance(){const data=await api('settings');form('Режим обслуживания',[
  ['maintenance_mode','Технические работы',data.maintenance_mode||'0','text',[['0','Выключены'],['1','Включены']]],
  ['sales_paused','Приостановить новые продажи',data.sales_paused||'0','text',[['0','Продажи открыты'],['1','Продажи приостановлены']]],
  ['maintenance_reason','Причина',data.maintenance_reason||'Обновляем магазин'],['maintenance_eta','Ориентир окончания',data.maintenance_eta||'Сообщим дополнительно'],
 ],v=>api('settings','POST',v));}
 function replacement(){form('Выдать замену по гарантии',[
  ['order','Номер заказа','','text'],['account_id','ID нового свободного аккаунта','','text'],['reason','Причина замены (3–500 символов)','','textarea'],
 ],v=>api('orders/'+positive(v.order)+'/replace','POST',{account_id:positive(v.account_id),reason:v.reason}));}
 function refund(){form('Вернуть оплату на баланс',[
  ['order','Номер заказа','','text'],['reason','Причина возврата (3–500 символов)','','textarea'],
 ],async v=>{const result=await api('orders/'+positive(v.order)+'/refund','POST',{reason:v.reason});categoryPriceResult=result.result?.pending?'Возврат ожидает согласования второго администратора.':'Запрос возврата обработан. Проверьте детали заказа.';});}
 async function discounts(){const data=await api('settings');form('Оптовая скидка',[
  ['wholesale_min_total','Сумма покупки для опта, ₽',data.wholesale_min_total||'500','number'],
  ['wholesale_pct','Скидка, % (0–50)',data.wholesale_pct||'15','number'],
 ],v=>api('settings','POST',v));}
 async function purge(){
  await go('stock');stockStatus='available';await load();
  inspect('Удаление невалидных аккаунтов','Удаляйте товары только после проверки результата. В разделе «Товары» отметьте конкретные свободные аккаунты и выберите «Удалить выбранные товары». Требуется ввод УДАЛИТЬ. Проданные и зарезервированные аккаунты сервер удалить не разрешит.');
 }
 async function broadcast(){const info=await publicApi('app-info');inspect('Рассылка через бота','В проекте уже есть рассылка с предпросмотром, подтверждением и остановкой. Откройте /admin в основном боте и выберите «Рассылка». Отправка из браузера не запускается.');if(info.bot_username){const a=node('a','Открыть бота →','terminal-link');a.href='https://t.me/'+info.bot_username;a.target='_blank';a.rel='noopener noreferrer';$('fields').append(a);}}
 async function payout(){await gateways();$('edit-title').textContent='Выручка и вывод средств';$('fields').prepend(node('p','Оплаты поступают в подключённые платёжные сервисы. Вывод выполняется в кабинете соответствующего провайдера; внутренний баланс покупателей не является доступной для вывода выручкой.','muted'));}
 async function infrastructure(kind){
  if(kind==='proxy')inspect('Прокси для проверки аккаунтов','Текущий Telethon-клиент использует прямое подключение. Пул SOCKS5 / HTTP не подключён. Интерфейс не показывает фиктивные прокси или результаты проверки.',[['Источник подключения','services/telethon_factory.py'],['Состояние пула','Не настроен']]);
  if(kind==='bot'){const info=await publicApi('app-info');inspect('Telegram-бот и webhook','Токен и Telegram API credentials хранятся в окружении сервера. Для изменения используйте защищённую конфигурацию сервиса, затем перезапуск.',[['Бот',info.bot_username?'@'+info.bot_username:'Не определён'],['Переменные','BOT_TOKEN · TELEGRAM_API_ID · TELEGRAM_API_HASH'],['Платёжные callback','Настраиваются у подключённого провайдера']]);}
  if(kind==='backup')inspect('Зашифрованная резервная копия','Проект использует restic для зашифрованных SQL-копий. Получайте копию через защищённый доступ к серверу. Ключ шифрования и полная база не выдаются обычным API браузера.',[['Инструкция','BACKUPS.md'],['Конфигурация','/etc/session-shope/backup.env'],['Расписание по умолчанию','Ежедневно около 04:00 МСК'],['Проверка','Настройте и проверьте deploy/backup_db.py на сервере']]);
 }
 function actionCard(number,title,subtitle,icon,actions){
  const card=node('section',undefined,'control-category'),heading=node('div',undefined,'control-category-heading'),identity=node('span',String(number).padStart(2,'0'),'control-number');heading.append(identity,node('div'));heading.lastChild.append(node('h3',title),node('p',subtitle,'muted'));heading.append(SbandUI.icon(icon));card.append(heading);
  for(const [text,detail,action,tone] of actions){const b=button('',action);b.classList.add('control-action');if(tone)b.classList.add('tone-'+tone);const words=node('span');words.append(node('strong',text),node('small',detail));const arrow=node('span',undefined,'control-arrow');arrow.append(SbandUI.icon('arrowUp'));b.append(words,arrow);card.append(b);}return card;
 }
 async function dashboard(){
  const revision=++generation;clearTimeout(stockTimer);content.setAttribute('aria-busy','true');content.replaceChildren();
  try{
   const data=await api('overview');if(revision!==generation)return;
   content.dataset.page='overview';const head=node('div',undefined,'control-intro');head.append(node('div','ОБЗОР / ОСНОВНОЙ МАГАЗИН','eyebrow'),node('h2','Всё под контролем.'),node('p','Реальные операции магазина. Единая точка управления.','muted'));content.append(head);
   const sales=(data.sales||[]).map(s=>s.currency==='RUB'?rub(s.amount):s.amount+' '+s.currency).join(' · ')||'0 ₽';
   const stats=node('div',undefined,'stats control-stats');for(const [name,value,note] of [['Выручка сегодня',sales,'Продажи · МСК'],['Активное наличие',data.stock,'Непроданные аккаунты'],['Возвраты на согласовании',data.approvals,'Требуют решения'],['Подключение чекера','Direct','Пул прокси не настроен']]){const c=node('div',undefined,'card');c.append(node('span',name,'muted'),node('strong',value),node('small',note));stats.append(c);}content.append(stats);
   const grid=node('div',undefined,'control-grid');grid.append(
    actionCard(1,'Товары и база аккаунтов','Импорт, качество и ценообразование','market',[
     ['Загрузить архивы аккаунтов','ZIP · .session + JSON · проверка перед публикацией',()=>go('imports'),'primary'],
     ['Проверить спамблок массово','Реальная очередь проверок через @SpamBot',()=>queueSpam(),'success'],
     ['Матрица цен и оптовые скидки','Цены по категориям и порог опта',()=>{inspect('Цены и скидки','Выберите действие.');$('fields').append(button('Цены по категориям',()=>{$('editor').close();return go('categories');}),button('Оптовые скидки',discounts));}],
     ['Экспорт непроданных сессий','ZIP с сессиями и JSON в личный чат',()=>sessionJobEditor('export')],
     ['Удалить невалидные аккаунты','Выбор товаров и обязательное подтверждение',purge,'danger'],
    ]),actionCard(2,'Заказы и финансы','Выдача, платежи и гарантийные решения','history',[
     ['Заказы и журнал оплат','Номера заказов, покупатели и история доступа',()=>go('orders')],
     ['Выдать замену вручную','По номеру заказа и ID нового аккаунта',replacement,'warning'],
     ['Платёжные шлюзы и кошельки','Реальное состояние способов пополнения',gateways],
     ['Выручка и вывод средств','Расчёты в кабинете платёжного провайдера',payout],
     ['Возврат на баланс покупателя','Проверка суммы и согласование по правилам',refund],
    ]),actionCard(3,'Пользователи и поддержка','Покупатели, промо и коммуникации','users',[
     ['Управление балансами','Поиск по Telegram ID или @username',()=>go('users')],
     ['Промокоды и скидки','Процентные и балансовые коды с лимитом',promoEditor],
     ['Заблокировать / разблокировать','Доступ покупателя к основному и партнёрским ботам',()=>go('user-bans'),'danger'],
     ['Очередь поддержки','Открытых обращений: '+data.tickets,()=>go('conversations')],
     ['Рассылка через бота','Предпросмотр и подтверждение в /admin',broadcast],
    ]),actionCard(4,'Система и безопасность','Подключения, доступ и журнал операций','info',[
     ['Прокси SOCKS5 / HTTP','Настройка подключения чекера',()=>infrastructure('proxy')],
     ['Telegram-бот и webhook','Конфигурация сервера без раскрытия токенов',()=>infrastructure('bot')],
     ['Режим обслуживания','Пауза продаж и технические работы',maintenance,'warning'],
     ['API и журнал действий','Администраторы, события и результаты операций',()=>go('system-audit')],
     ['Резервная копия базы','Зашифрованные SQL-копии через restic',()=>infrastructure('backup')],
    ]));content.append(grid);
   const foot=node('p','Ключи и резервные копии управляются на сервере. Все операции с товарами и балансами проходят серверную проверку доступа.','control-footnote');content.append(foot);
  }catch(e){if(revision===generation)SbandUI.errorBox(content,e.message,dashboard);}finally{if(revision===generation)content.removeAttribute('aria-busy');}
 }
 async function ownView(){
  const revision=++generation;content.replaceChildren(button('← Центр управления',()=>go('overview')));
  try{
   if(page==='user-bans'){
    const data=await api('user-bans');if(revision!==generation)return;content.append(node('h2','Блокировки пользователей'));
    content.append(button('Изменить доступ пользователя',()=>form('Доступ пользователя',[
     ['user_id','Telegram ID','','text'],['enabled','Действие','1','text',[['1','Заблокировать'],['0','Снять блокировки']]],['reason','Причина','','textarea'],
    ],v=>api('user-bans','POST',{user_id:positive(v.user_id),enabled:v.enabled==='1',reason:v.reason})),true));
    for(const b of data.items)row(content,'ID '+b.user_id,b.reason,b.active?'Заблокирован':'Разблокирован');
    if(!data.items.length)content.append(node('p','Блокировок пока нет.','muted'));
   }else if(page==='system-audit'){
    const data=await api('audit');if(revision!==generation)return;content.append(node('h2','Журнал действий'));
    const entries=data.items||data;for(const item of entries)row(content,labels[item.action]||item.action,'Администратор '+item.admin_id+' · '+item.target_type+' #'+item.target_id+' · '+item.created_at,typeof item.details==='string'?item.details:JSON.stringify(item.details));
    if(!entries.length)content.append(node('p','Событий пока нет.','muted'));
   }else await maintenance();
  }catch(e){SbandUI.errorBox(content,e.message,ownView);}
 }
 load=async function(){if(page==='overview'&&!window.SBAND_HELPER)return dashboard();if(ownPages.has(page))return ownView();return previousLoad();};
 // Enhance the existing ZIP form without changing its upload/preview transaction.
 const observer=new MutationObserver(()=>{
  for(const input of content.querySelectorAll('input[type=file]')){
   if(input.dataset.dropReady)return;input.dataset.dropReady='1';const target=input.closest('label');if(!target)continue;target.classList.add('archive-dropzone');target.prepend(node('strong','Перетащите ZIP сюда или выберите файл'));
   target.addEventListener('dragover',e=>{e.preventDefault();target.classList.add('drag-over');});target.addEventListener('dragleave',()=>target.classList.remove('drag-over'));
   target.addEventListener('drop',e=>{e.preventDefault();target.classList.remove('drag-over');const file=e.dataTransfer?.files[0];if(!file||!file.name.toLowerCase().endsWith('.zip')){showError(Error('Нужен ZIP-архив.'));return;}if(file.size>8*1024*1024){showError(Error('Максимальный размер — 8 МБ.'));return;}const transfer=new DataTransfer();transfer.items.add(file);input.files=transfer.files;input.dispatchEvent(new Event('change',{bubbles:true}));});
  }
 });observer.observe(content,{childList:true,subtree:true});
})();
