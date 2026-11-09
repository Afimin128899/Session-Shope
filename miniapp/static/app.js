'use strict';
(() => {
  const $ = s => document.querySelector(s);
  const tg = window.Telegram?.WebApp;
  const state = { tab: 'home', wholesale:{minimum:'500',percent:'15'}, ready: false, me: null, items: [], page: 0, category: '', orderPage: 0, orders: [], busy: false, revision: 0, invoice: null, refreshing: false, dialogRevision: 0 };
  const labels = { home:'Главная', messages:'Сообщения', catalog: 'Каталог', favorites: 'Избранное', cart: 'Корзина', orders: 'Покупки', profile: 'Профиль' };
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const num = v => new Intl.NumberFormat(window.SbandI18n.locale, { maximumFractionDigits: 2 }).format(Number(v || 0));
  const rub = v => num(v) + ' ₽';
  const spamLabel = check => check?.running ? SbandT('Проверяется…') : check?.status === 'clear' ? SbandT('Нет спамблока') : check?.status === 'limited' ? SbandT('Есть спамблок') : check?.status === 'permanent' ? SbandT('Вечный спамблок') : (check?.label || SbandT('Не проверен'));
  const spamTime = check => check?.checked_at ? new Date(check.checked_at).toLocaleString(window.SbandI18n.locale,{timeZone:'Europe/Moscow'})+SbandT(" МСК") : SbandT("Пока не проверялся");
  let toastTimer, searchTimer;
  function toast(text) { $('#toast').textContent = text; $('#toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 4500); }
  function notice(text = '') { $('#notice').textContent = text; $('#notice').hidden = !text; }
  function reset(text) {
    document.body.classList.remove('maintenance-mode');
    if($('#demo-mode-notice'))$('#demo-mode-notice').hidden=true;
    document.querySelectorAll('[data-demo]').forEach(button=>button.hidden=true);
    window.SBAND_USER=null; document.dispatchEvent(new Event('sband-logout')); state.ready = false; state.me = null; state.items = []; state.recentItems=[]; state.supportRows=[]; state.supportTicket=null; state.orders = []; state.invoice = null; state.revision++;
    $('#header-balance').textContent = '— ₽'; $('#profile-balance').textContent = '— ₽'; $('#home-balance').textContent='— ₽'; $('#home-countries').replaceChildren(); $('#recent-products').replaceChildren(); $('#country-feature').replaceChildren(); $('#catalog-grid').replaceChildren(); $('#orders-list').replaceChildren();
    document.querySelectorAll('.page').forEach(el => { el.hidden = true; }); $('#login-panel').hidden = false;
    $('#purchase-dialog').close(); $('#dialog-content').replaceChildren(); $('#sync-state').textContent = SbandT("Нужен вход"); notice(text);
  }
  const api = (path, options = {}) => window.SbandRequest(path, options);
  const post = (path, body, method = 'POST') => api(path, { method, body: JSON.stringify(body) });
  function error(e) { if(e.code==='maintenance'){showMaintenance(e.details?.shop_status);return;} if(e.code==='sales_paused')loadMe().then(render).catch(()=>{}); if (e.code === 'unauthorized') reset(e.message); else notice(e.message || SbandT("Проверь соединение и попробуй ещё раз.")); }
  function openBot(id) {
    const username = state.me?.bot_username;
    if (!username || !/^[a-zA-Z0-9_]+$/.test(username)) { toast(SbandT("Открой Telegram-бота, из которого запущен магазин.")); return; }
    const url = 'https://t.me/' + username + (id ? '?start=order_' + id : '');
    if (tg?.openTelegramLink) tg.openTelegramLink(url); else window.open(url, '_blank', 'noopener,noreferrer');
  }
  async function loadMe() {
    const revision=state.meRevision=(state.meRevision||0)+1;
    const data = await api('me');if(revision!==state.meRevision)return; if(state.me?.user?.id!==data.user.id)state.recentItems=[]; state.me = data; window.SbandI18n.setLanguage(data.language); updateSalesStatus(data.shop_status); window.SBAND_USER=data; document.dispatchEvent(new CustomEvent('sband-identity',{detail:data}));
    document.querySelectorAll('[data-demo]').forEach(button=>button.hidden=!data.is_admin);
    if($('#demo-mode-notice'))$('#demo-mode-notice').hidden=!data.test_mode_active;
    const initial = (data.user.first_name || 'S').slice(0, 1).toUpperCase();
    $('#avatar').textContent = initial; $('#profile-avatar').textContent = initial;
    $('#profile-name').textContent = data.user.first_name || SbandT("Покупатель"); $('#profile-username').textContent = data.user.username ? '@' + data.user.username : SbandT("Покупатель Sband ACCS");
    $('#profile-id').textContent = data.user.id; $('#header-balance').textContent = rub(data.balance); $('#profile-balance').textContent = rub(data.balance); $('#home-balance').textContent=rub(data.balance);
    $('#welcome-bonus').hidden = !(Number(data.welcome_bonus) > 0);
    $('#profile-usdt').textContent = num(data.balance_usdt) + ' USDT'; $('#version').textContent = 'v' + data.version;
  }
  function updateSalesStatus(status={}) {
    $('#sales-notice').hidden=!status.sales_paused;
    $('#sales-reason').textContent=status.sales_reason||'';
  }
  function showMaintenance(status={}) {
    state.ready=false;state.revision++;state.dialogRevision++;
    document.body.classList.add('maintenance-mode');$('#maintenance-feedback').textContent='';
    document.querySelectorAll('.page').forEach(el=>el.hidden=true);
    $('#login-panel').hidden=true;$('#maintenance-page').hidden=false;
    $('#purchase-dialog').close();$('#dialog-content').replaceChildren();
    $('#maintenance-reason').textContent=status.reason||'';
    $('#maintenance-eta').textContent=status.eta||'';
    $('#sync-state').textContent=SbandT("🛠 Технические работы");notice();
  }
  function render() {
    $('#catalog-grid').innerHTML = state.items.map(item => SbandT("<article class=\"account-card\"><div class=\"card-head\"><span class=\"flag\" aria-hidden=\"true\">{0}</span><div class=\"card-head-right\">{1}<button class=\"heart {2}\" data-favorite=\"{3}\" aria-label=\"{4}\" aria-pressed=\"{5}\">{6}</button></div></div><h3>{7}</h3><span class=\"stock-tag {8}\">{9}</span><button class=\"feature-link\" data-features=\"{10}\">Характеристики {11}</button><div class=\"card-phone\">{12}</div><div class=\"spam-line {13}\" data-spam-status=\"{10}\" aria-live=\"polite\" title=\"{14}\">Спамблок: {15}</div><div class=\"ids\"><div><span>Товар</span><b>{16}</b></div><div><span>Telegram ID</span><b>{17}</b></div></div><div class=\"card-bottom\"><div>{18}<span class=\"card-price\">{19}<small>₽</small></span></div><button class=\"buy-button {20}\" data-add=\"{21}\" {22} aria-label=\"{23} {24}\">{25}</button></div>{26}</article>",window.SbandCountryArt(item),item.characteristics?.is_premium ? '<span class="premium-badge">Premium</span>' : '',item.favorite ? 'selected' : '',item.id,item.favorite ? SbandT("Убрать из избранного") : SbandT("В избранное"),item.favorite,item.favorite ? '♥' : '♡',esc(window.SbandCountryName(item)),item.available ? '' : 'unavailable',item.available ? SbandT("В наличии") : SbandT("Недоступен"),item.id,item.characteristics?.warranty_hours ? '· '+item.characteristics.warranty_hours+SbandT(" ч гарантии") : '↗',esc(item.phone),['limited','permanent'].includes(item.characteristics?.spam_check?.status) ? 'spam-limited' : ['unknown','error'].includes(item.characteristics?.spam_check?.status) ? 'spam-unverified' : '',esc(spamTime(item.characteristics?.spam_check)),esc(spamLabel(item.characteristics?.spam_check)),esc(item.product_id),esc(item.telegram_user_id || SbandT("Не сохранён")),Number(item.discount)>0 ? `<span class="old-price"><s>${rub(item.original_price)}</s><span class="discount-badge">−${num(item.discount)}%</span></span>` : '',num(item.price),item.in_cart ? 'added' : '',item.id,!item.available || state.me?.shop_status?.sales_paused ? 'disabled' : '',item.in_cart ? SbandT("Обновить резерв") : SbandT("В корзину"),esc(window.SbandCountryName(item)),item.in_cart ? '✓ '+SbandT('В корзине') : '+ '+SbandT('В корзину'),item.in_cart ? SbandT("<div class=\"reserve\" data-until=\"{0}\"></div><button class=\"remove-button\" data-remove=\"{1}\">Убрать из корзины</button>",esc(item.reserved_until || ''),item.id) : '')).join('');
    $('#catalog-empty').hidden = state.items.length > 0;
    const empty = state.tab === 'cart' ? [SbandT("Корзина пока пуста"), SbandT("Добавь аккаунт — он будет зарезервирован на 5 минут.")] : state.tab === 'favorites' ? [SbandT("Сохрани то, что нравится"), SbandT("Нажми ♡ в каталоге. О снижении цены сообщим в боте.")] : [SbandT("Пока ничего не найдено"), SbandT("Попробуй изменить фильтры или загляни позже.")];
    $('#empty-title').textContent = empty[0]; $('#empty-copy').textContent = empty[1];
    $('#cart-summary').hidden = state.tab !== 'cart' || !state.items.length;
    $('#cart-count').textContent = SbandT("· {0} шт.",state.items.length);
    // Integer kopecks keep the displayed quote equal to the server's Decimal total.
    $('#cart-total').textContent = rub(state.items.reduce((n, item) => n + Math.round(Number(item.price) * 100), 0) / 100);
    countdown();
  }
  function recentKey(){return 'sband_recent_'+state.me?.user?.id;}
  function recentIds(){try{return JSON.parse(sessionStorage.getItem(recentKey())||'[]').filter(Number.isSafeInteger).slice(0,8);}catch(_){return [];}}
  function rememberProduct(item){try{sessionStorage.setItem(recentKey(),JSON.stringify([item.id,...recentIds().filter(id=>id!==item.id)].slice(0,8)));}catch(_){} }
  function scene(item){return 'scene-'+window.SbandCountryCode(item);}
  function countryTile(cat,extra=''){
    const item={category:cat.slug,name:cat.name},name=window.SbandCountryName(item),parts=name.split(' · '),title=parts[0].replace(/[\u{1F1E6}-\u{1F1FF}]{2}/gu,'').trim();
    return `<button class="country-tile ${scene(item)} ${extra}" data-category="${esc(cat.slug)}" aria-label="${esc(name)}"><span class="tile-art" aria-hidden="true"></span>${window.SbandCountryArt(item)}<span class="tile-caption"><strong>${esc(title)}</strong><small>${extra?esc(parts[1]||SbandT('В наличии')):SbandT('В наличии')+': '+(Number(cat.count)||0)}</small></span>${cat.min_price!=null?`<b class="tile-price">${SbandT('от')} ${rub(cat.min_price)}</b>`:''}</button>`;
  }
  function productCount(value){
    const n=Number(value)||0;
    if(window.SbandI18n.language==='en')return n+(n===1?' product':' products');
    return n+' '+(n%10===1&&n%100!==11?'товар':[2,3,4].includes(n%10)&&![12,13,14].includes(n%100)?'товара':'товаров');
  }
  function renderDiscovery(){
    $('#departments-grid').innerHTML=(state.departments||[]).map(d=>`<button class="department-card" data-department="${esc(d.slug)}"><span aria-hidden="true">${esc(d.emoji||'◇')}</span><strong>${esc(SbandT(d.name))}</strong><small class="${d.is_active?'':'pending-department'}">${d.is_active?productCount(d.count):SbandT('В разработке')}</small></button>`).join('');
    const cats=(state.categories||[]).slice().sort((a,b)=>Number(b.count)-Number(a.count));
    $('#home-countries').innerHTML=cats.filter((c,i,list)=>Number(c.count)>0&&list.findIndex(other=>window.SbandCountryCode({category:other.slug,name:other.name})===window.SbandCountryCode({category:c.slug,name:c.name}))===i).slice(0,3).map(c=>countryTile(c)).join('')||`<p class="muted">${SbandT('Пока ничего не найдено')}</p>`;
    const codes=new Set(cats.map(c=>window.SbandCountryCode({category:c.slug,name:c.name})).filter(c=>c!=='unknown'));
    $('#country-count').textContent=codes.size;$('#stock-count').textContent=cats.reduce((n,c)=>n+Number(c.count),0);
    const featured=cats.find(c=>Number(c.count)>0);
    $('#country-feature').innerHTML=featured?`<h2>${SbandT('Сейчас в наличии')}</h2>`+countryTile(featured,'featured-country'):'';
    document.querySelectorAll('#categories .category').forEach(button=>{
      const cat=cats.find(c=>c.slug===button.dataset.category);if(!cat)return;
      button.classList.add('scenic-category',scene({category:cat.slug,name:cat.name}));
      const parts=window.SbandCountryName({category:cat.slug,name:cat.name}).split(' · ');button.setAttribute('aria-label',parts.join(' · '));button.querySelector('span:not(.all-countries-icon)').textContent=parts[0].replace(/[\u{1F1E6}-\u{1F1FF}]{2}/gu,'').trim();button.querySelector('small').textContent=(parts[1]?parts[1]+' · ':'')+cat.count;
      button.classList.toggle('stock-hidden',!!state.onlyStockCountries&&Number(cat.count)===0);
    });
    const recent=recentIds().map(id=>(state.recentItems||[]).find(i=>i.id===id)||state.items.find(i=>i.id===id)).filter(i=>i&&i.available);
    $('#recent-section').hidden=!recent.length;
    $('#recent-products').innerHTML=recent.map(item=>`<button class="recent-product ${scene(item)}" data-features="${item.id}"><span class="tile-art" aria-hidden="true"></span>${window.SbandCountryArt(item)}<strong>${esc(window.SbandCountryName(item).split(' · ')[0])}</strong><b>${rub(item.price)}</b></button>`).join('');
  }
  async function openDepartment(slug){
    try{
      const d=(await api('departments')).items?.find(item=>item.slug===slug);
      if(!d)return;
      modal(`<h2 id="dialog-title">${esc(SbandT(d.name))}</h2><p>${d.is_active?productCount(d.count):SbandT('Раздел в разработке. Скоро здесь появятся товары.')}</p>`);
    }catch(e){error(e);}
  }
  async function loadSupport(append=false){
    const revision=state.supportRevision=(state.supportRevision||0)+1,page=append?(state.supportPage||0)+1:0;
    const data=await api('support?page='+page);
    if(revision!==state.supportRevision||state.tab!=='messages'||!state.ready)return;
    state.supportPage=page;state.supportRows=append?[...(state.supportRows||[]),...data.items.slice(0,5)]:data.items.slice(0,5);
    $('#support-list').innerHTML=state.supportRows.map(t=>`<button class="support-thread" data-support-ticket="${t.id}"><strong>${SbandT('Обращение')} #${t.id}</strong><span>${t.purchase_id?SbandT('Заказ')+' #'+t.purchase_id:SbandT('Общий вопрос')}</span><small>${SbandT({open:'Ждёт ответа',waiting_user:'Поддержка ответила',closed:'Закрыто'}[t.status]||'Ждёт ответа')}</small></button>`).join('')||`<p class="muted">${SbandT('Обращений пока нет')}</p>`;
    $('#support-more').hidden=data.items.length<=5;
  }
  async function refreshSupport(){
    if(!(state.supportPage>0))await loadSupport();
    if(!$('#support-reply')||!state.supportTicket||state.supportBefore||$('#reply-body').value.trim())return;
    const id=state.supportTicket,revision=state.dialogRevision;
    const data=await api('support/'+id);
    if(revision===state.dialogRevision&&$('#support-reply')&&!$('#reply-body').value.trim()&&(data.messages[0]?.id||0)!==state.supportNewest)await openSupport(id);
  }
  async function openSupport(id,before=0){
    const revision=++state.dialogRevision;
    try{
      const d=await api('support/'+id+(before?'?before='+before:''));
      if(revision!==state.dialogRevision||!state.ready)return;
      state.supportTicket=id;state.supportBefore=before;state.supportNewest=d.messages[0]?.id||0;
      modal(`<h2 id="dialog-title">${SbandT('Обращение')} #${id}</h2><p class="muted">${SbandT('Только вы и поддержка SBAND')}</p><button class="secondary-button" id="support-refresh-thread">${SbandT('Обновить')}</button><div class="support-history">${d.messages.slice().reverse().map(m=>`<article class="support-bubble ${m.author_role==='admin'?'support-answer':''}"><small>${SbandT({user:'Вы',admin:'Поддержка',system:'Система'}[m.author_role]||'Система')}</small><p>${esc(m.body)}</p>${m.has_photo?`<small>${SbandT('Скриншот доступен в боте')}</small>`:''}</article>`).join('')}</div>${d.has_more?`<button class="secondary-button" id="support-older">${SbandT('Ранее')}</button>`:''}<form id="support-reply"><label for="reply-body">${SbandT('Сообщение поддержке')}</label><textarea id="reply-body" rows="3" maxlength="500" required></textarea><p id="reply-error" role="alert" hidden></p><button type="submit" class="primary-button">${SbandT('Отправить')}</button></form>`);
      $('#support-refresh-thread').onclick=()=>{if($('#reply-body').value.trim()){toast(SbandT('Сначала отправьте или очистите черновик.'));return;}openSupport(id);};
      if($('#support-older'))$('#support-older').onclick=()=>openSupport(id,d.messages.at(-1).id);
      $('#support-reply').onsubmit=async e=>{e.preventDefault();const form=e.currentTarget,button=form.querySelector('button');button.disabled=true;try{await post('support/'+id+'/reply',{body:$('#reply-body').value});await openSupport(id);if(state.tab==='messages')await loadSupport();}catch(e){const el=$('#reply-error');if(el){el.textContent=e.message;el.hidden=false;}}finally{if(button.isConnected)button.disabled=false;}};
    }catch(e){error(e);}
  }
  function countdown() {
    document.querySelectorAll('[data-until]').forEach(el => {
      const seconds = Math.max(0, Math.floor((Date.parse(el.dataset.until) - Date.now()) / 1000));
      el.textContent = seconds ? SbandT("Резерв {0}:{1}",Math.floor(seconds / 60),String(seconds % 60).padStart(2, '0')) : SbandT("Резерв истёк · нажми ✓, чтобы обновить");
    });
    if (state.tab === 'cart') $('#checkout-cart').disabled = !!state.me?.shop_status?.sales_paused || !state.items.length || state.items.some(i => !i.available || !(Date.parse(i.reserved_until) > Date.now()));
  }
  async function loadMarket(append = false) {
    if (!['home','catalog', 'favorites', 'cart'].includes(state.tab)) return;
    const rev = ++state.revision, tab = state.tab, page = append ? state.page + 1 : 0;
    const query = new URLSearchParams({ page });
    if (tab === 'catalog') { query.set('category', state.category); query.set('q', $('#search').value); query.set('sort', $('#sort').value); query.set('min_price', $('#min-price').value); query.set('max_price', $('#max-price').value); query.set('premium',$('#premium-filter').value);query.set('min_age',$('#age-filter').value); }
    const [data,departments]=await Promise.all([api((['home','catalog'].includes(tab)?'catalog':tab)+'?'+query),api('departments')]);
    state.departments=departments.items||[];
    if (rev !== state.revision || state.tab !== tab || !state.ready) return;
    state.categories=data.categories;
    state.page = page; state.items = append ? [...state.items, ...data.items] : data.items;
    $('#total-count').textContent = tab === 'catalog' ? data.categories.reduce((n, c) => n + Number(c.count), 0) : state.items.length;
    $('#categories').innerHTML = [{ slug: '', name: SbandT("Все аккаунты"), count: data.categories.reduce((n, c) => n + Number(c.count), 0) }, ...data.categories.slice().sort((a,b)=>Number(b.count)-Number(a.count))].map(c => `<button class="category ${c.slug === state.category ? 'active' : ''}" data-category="${esc(c.slug)}">${c.slug ? window.SbandCountryArt({category:c.slug,name:c.name}) : '<span class="all-countries-icon" aria-hidden="true">◎</span>'}<span>${esc(window.SbandCountryName({category:c.slug,name:c.name}))}</span><small>${c.count}</small></button>`).join('');
    $('#countries-toggle').textContent=SbandT($('#categories').classList.contains('expanded')?'Свернуть страны ↑':'Все страны ↓');
    $('#countries-toggle').hidden=data.categories.length<6;
    $('#load-more').hidden = !data.has_more; render(); renderDiscovery();
    if(tab==='home'&&recentIds().length){
      const results=await Promise.allSettled(recentIds().slice(0,6).map(id=>api('products/'+id)));
      if(rev!==state.revision||state.tab!==tab||!state.ready)return;
      state.recentItems=results.filter(r=>r.status==='fulfilled').map(r=>r.value);renderDiscovery();
    }
  }
  async function loadOrders(append = false) {
    const revision=state.orderRevision=(state.orderRevision || 0)+1;
    const page = append ? state.orderPage + 1 : 0, data = await api('orders?page=' + page+'&q='+encodeURIComponent($('#order-search').value));
    if (!state.ready || revision!==state.orderRevision) return;
    state.orderPage = page; state.orders = append ? [...state.orders, ...data.items] : data.items;
    $('#orders-list').innerHTML = state.orders.map(o => SbandT("<article class=\"order-row\"><div><h3>{0} · #{1}</h3><p>{2} · {3}<br>{4}</p></div><button data-order=\"{5}\">Открыть <svg class=\"arrow\" viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M6 18 18 6M6 6h12v12\"/></svg></button></article>",esc(o.name),o.id,esc(o.status_label),esc(o.date),o.paid_amount !== null ? num(o.paid_amount) + ' ' + esc(o.currency) : SbandT("Сумма не сохранена"),o.id)).join('');
    $('#orders-empty').hidden = state.orders.length > 0; $('#more-orders').hidden = !data.has_more;
  }
  function showPage() {
    document.body.dataset.storeTab=state.tab;
    $('#market-page').hidden = !['catalog', 'favorites', 'cart'].includes(state.tab);
    $('#orders-page').hidden = state.tab !== 'orders'; $('#profile-page').hidden = state.tab !== 'profile'; $('#messages-page').hidden=state.tab!=='messages';
    document.querySelectorAll('[data-tab]').forEach(el => el.classList.toggle('active', el.dataset.tab === state.tab));
    $('#breadcrumb').textContent = SbandT(labels[state.tab]); $('#home-page').hidden=state.tab!=='home'; $('#benefits').hidden=true; $('#filters').hidden = state.tab !== 'catalog';
    $('#market-title').textContent = state.tab === 'catalog' ? SbandT("Аккаунты") : SbandT(labels[state.tab]);
    $('#market-kicker').textContent = state.tab === 'cart' ? SbandT("РЕЗЕРВ НА 5 МИНУТ") : state.tab === 'favorites' ? SbandT("ТО, ЧТО НРАВИТСЯ") : SbandT("ВЫБЕРИ СВОЙ");
    $('#collection-note').hidden = state.tab === 'catalog';
    $('#collection-note').textContent = state.tab === 'cart' ? SbandT("Оплата всей корзины за один раз. После истечения резерва нажми ✓ на каждом аккаунте.") : SbandT("Сообщим в боте, если базовая цена снизится. Убери ♡, чтобы отключить уведомления.");
  }
  async function switchTab(tab) {
    if (!state.ready || !labels[tab]) return;
    state.tab = tab; state.revision++; state.page = 0; state.items = []; showPage(); notice();
    $('#catalog-grid').replaceChildren(); $('#cart-summary').hidden = true;
    try { if (tab === 'messages') await loadSupport(); else if (tab === 'orders') await loadOrders(); else if (tab !== 'profile') await loadMarket(); } catch (e) { error(e); }
    window.scrollTo({ top: 0, behavior: 'instant' });
  }
  function modal(html) { state.dialogRevision++; $('#dialog-content').innerHTML = html; if (!$('#purchase-dialog').open) $('#purchase-dialog').showModal(); }
  function dialogError(e) { if(e.code==='maintenance'){showMaintenance(e.details?.shop_status);return;} if (e.code === 'unauthorized') { reset(e.message); return; } const el = $('#dialog-error'); if (el) { el.textContent = e.message; el.hidden = false; } else error(e); }
  async function checkout() {
    if (!state.items.length || state.busy) return;
    const items = state.items.map(i => ({ account_id: i.id, price: i.price, warranty_hours:i.characteristics?.warranty_hours ?? null, spam_status:i.characteristics?.spam_check?.status || 'not_checked' }));
    let promo = null;
    const base = items.reduce((n,i)=>n+Math.round(Number(i.price)*100),0)/100;
    const bulk = base>=Number(state.wholesale.minimum) ? Number(state.wholesale.percent) : 0;
    const sum = rate => items.reduce((n,i) => n + Math.round(Math.round(Math.round(Number(i.price)*100)*(10000-Math.round(bulk*100))/10000)*(10000-Math.round(Number(rate)*100))/10000),0)/100;
    const total = sum(0);
    modal(SbandT("<h2 id=\"dialog-title\">Подтвердить покупку</h2><p>{0} аккаунт(ов). После оплаты они появятся в покупках и Telegram-боте.</p><p>{1}</p><p>Гарантия на проблемы со входом в пределах срока. Решение по обращению принимает поддержка после проверки.</p><div class=\"info\"><span>К оплате</span><b id=\"quoted-total\">{2}</b></div><div class=\"info\"><span>Баланс</span><b>{3}</b></div><p>Оптовая скидка: {4}%. Порог {5} до применения промокода.</p><label for=\"coupon-code\">Промокод (необязательно)</label><input id=\"coupon-code\" maxlength=\"64\" placeholder=\"Например, SBAND10\"><button id=\"preview-coupon\" class=\"secondary-button\">Проверить промокод</button><p id=\"coupon-result\" aria-live=\"polite\"></p><p id=\"dialog-error\" class=\"dialog-error\" role=\"alert\" hidden></p><button id=\"confirm-purchase\" class=\"primary-button\">Оплатить {6} <svg class=\"arrow\" viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M6 18 18 6M6 6h12v12\"/></svg></button>",items.length,state.items.map(i=>esc(i.product_id)+SbandT(": гарантия ")+(i.characteristics?.warranty_hours == null ? SbandT("не указана") : i.characteristics.warranty_hours+SbandT(" ч"))+SbandT("; спамблок: ")+esc(spamLabel(i.characteristics?.spam_check))).join('<br>'),rub(total),rub(state.me.balance),bulk,rub(state.wholesale.minimum),rub(total)));
    const confirmButton = $('#confirm-purchase');
    const applyCartLimit = () => {
      const over = sum(promo?.value || 0) > 10000;
      confirmButton.disabled = over;
      if (over) { $('#dialog-error').textContent = SbandT('Сумма корзины не должна превышать 10 000 ₽.'); $('#dialog-error').hidden = false; }
      return over;
    };
    applyCartLimit();
    $('#preview-coupon').onclick = async () => {
      if (state.busy) return;
      confirmButton.disabled = true; $('#preview-coupon').disabled = true;
      promo = null; $('#dialog-error').hidden = true;
      const typed = $('#coupon-code').value;
      try {
        const result = await post('promo/preview',{code:typed});
        if (!confirmButton.isConnected || $('#coupon-code').value !== typed) return;
        if (result.kind === 'balance') {
          $('#coupon-result').textContent = SbandT("Этот код пополнит баланс на ")+rub(result.value)+SbandT(". Активируй его в профиле, затем вернись к оплате.");
        } else {
          promo = result;
          $('#coupon-result').textContent = SbandT("Дополнительная скидка ")+num(result.value)+SbandT("%. Экономия ")+rub(total-sum(result.value))+SbandT(". Код будет использован только после успешной покупки.");
        }
      } catch (e) { if (confirmButton.isConnected) dialogError(e); }
      finally {
        if (confirmButton.isConnected) {
          $('#quoted-total').textContent = rub(sum(promo?.value || 0));
          confirmButton.textContent = SbandT("Оплатить ")+rub(sum(promo?.value || 0));
          applyCartLimit(); $('#preview-coupon').disabled = false;
        }
      }
    };
    $('#coupon-code').oninput = () => { promo = null; $('#dialog-error').hidden = true; $('#quoted-total').textContent = rub(total); confirmButton.textContent = SbandT("Оплатить ")+rub(total); $('#coupon-result').textContent = ''; applyCartLimit(); };
    $('#confirm-purchase').onclick = async () => {
      if (state.busy || applyCartLimit()) return; state.busy = true; $('#confirm-purchase').disabled = true;
      try {
        const result = await post('cart/checkout', { items, expected_total:sum(promo?.value || 0).toFixed(2), ...(promo ? {promo_code:promo.code} : {}) });
        modal(SbandT("<div class=\"success-icon\">✓</div><h2 id=\"dialog-title\">Покупка готова!</h2><p>Заказов: {0}. Списано {1}.<br>Остаток: {2}.</p><button class=\"primary-button\" id=\"show-my-orders\">Мои покупки <svg class=\"arrow\" viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M6 18 18 6M6 6h12v12\"/></svg></button>",result.order_ids.length,rub(result.paid_amount),rub(result.balance)));
        $('#show-my-orders').onclick = () => { $('#purchase-dialog').close(); switchTab('orders'); };
        tg?.HapticFeedback?.notificationOccurred('success'); await loadMe(); await loadMarket();
      } catch (e) { dialogError(e); if ($('#confirm-purchase')) { $('#confirm-purchase').disabled = ['sold', 'price_changed', 'reservation_expired', 'cart_changed', 'terms_changed', 'invalid_promo'].includes(e.code); } await loadMarket().catch(() => {}); }
      finally { state.busy = false; }
    };
  }
  async function showOrder(id) {
    const dialogRevision = ++state.dialogRevision;
    try {
      const o = await api('orders/' + id);
      if (dialogRevision !== state.dialogRevision) return;
      modal(SbandT("<h2 id=\"dialog-title\">Заказ #{0}</h2><p>{1} · {2}</p><div class=\"info\"><span>ID товара</span><b>{3}</b></div><div class=\"info\"><span>Telegram ID</span><b>{4}</b></div><div class=\"info\"><span>Номер</span><b class=\"secret-value\">{5}</b></div><div class=\"info\"><span>Пароль 2FA</span><b class=\"secret-value\" id=\"order-password\">{6}</b></div>{7}<p>Код входа, завершение покупки и поддержка доступны в Telegram-боте.</p><button class=\"primary-button\" data-bot-order=\"{8}\">Открыть в боте <svg class=\"arrow\" viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M6 18 18 6M6 6h12v12\"/></svg></button>",o.id,esc(o.status_label),esc(o.date),esc(o.product_id || '—'),esc(o.telegram_user_id || SbandT("Не сохранён")),esc(o.number || '—'),o.status === 'refunded' ? SbandT("Доступ закрыт") : '••••••',o.status !== 'refunded' ? SbandT("<button id=\"show-password\" class=\"secondary-button\">Показать пароль</button>") : '',o.id));
      const warranty = o.warranty || {};
      $('#dialog-content').insertAdjacentHTML('beforeend', SbandT("<div class=\"info\"><span>Спамблок при покупке</span><b>{0}</b></div><p class=\"muted\">{1}</p>",esc(spamLabel(o.characteristics?.spam_check)),esc(spamTime(o.characteristics?.spam_check))));
      $('#dialog-content').insertAdjacentHTML('beforeend', SbandT("<div class=\"warranty-box\"><b>Гарантия: {0}</b>{1}<p>{2}</p>{3}</div><button id=\"write-review\" class=\"secondary-button\">{4}</button>",esc(warranty.label || SbandT("Срок не сохранён")),warranty.until ? SbandT("<p>До {0} МСК</p>",esc(new Date(warranty.until).toLocaleString(window.SbandI18n.locale,{timeZone:'Europe/Moscow'}))) : '',esc(SbandT(warranty.policy || '')),warranty.active ? SbandT("<button id=\"warranty-claim\" class=\"secondary-button\">Обратиться по гарантии</button>") : '',o.review ? SbandT("Изменить отзыв") : SbandT("Оставить отзыв")));
      $('#write-review').onclick = () => reviewEditor(o);
      if ($('#warranty-claim')) $('#warranty-claim').onclick = () => warrantyEditor(o);
      if ($('#show-password')) $('#show-password').onclick = () => { $('#order-password').textContent = o.password || SbandT("Не установлен"); $('#show-password').hidden = true; };
    } catch (e) { error(e); }
  }
  async function features(id) {
    const dialogRevision = ++state.dialogRevision;
    try {
      const item=await api('products/'+id),c=item.characteristics || {}; rememberProduct(item);
      if (dialogRevision !== state.dialogRevision) return;
      modal(SbandT("<div class=\"product-cover\">{0}<span>TELEGRAM ACCOUNT</span></div><h2 id=\"dialog-title\">{1}</h2><p>{2} · Telegram ID {3}</p><div class=\"info\"><span>Регистрация</span><b>{4}</b></div><div class=\"info\"><span>Premium</span><b>{5}</b></div><div class=\"info\"><span>2FA</span><b>{6}</b></div><div class=\"info\"><span>Спамблок</span><b>{7}</b></div><p class=\"muted\">{8}. Источник: @SpamBot. Состояние может измениться после проверки.</p><div class=\"info\"><span>Гарантия</span><b>{9}</b></div><p>{10}</p><p>После оплаты данные появятся в покупках. Код входа выдаёт бот. После входа смените пароль и привяжите свою почту. Premium указан на момент проверки и может измениться.</p><button id=\"product-add\" class=\"primary-button\">В корзину · {11}</button><button id=\"share-product\" class=\"secondary-button\">Поделиться товаром</button>",window.SbandCountryArt(item),esc(window.SbandCountryName(item)),esc(item.product_id),esc(item.telegram_user_id || SbandT("Не сохранён")),esc(c.registration_date || SbandT("Не указана")),c.is_premium == null ? SbandT("Не проверено") : c.is_premium ? SbandT("Да") : SbandT("Нет"),esc(SbandT(c.two_fa) || SbandT("Не указано")),esc(spamLabel(c.spam_check)),esc(spamTime(c.spam_check)),c.warranty_hours == null ? SbandT("Не указана") : c.warranty_hours+SbandT(" ч"),esc(c.note),rub(item.price)));
      $('#product-add').onclick=async()=>{try{await post('cart',{account_id:id});$('#purchase-dialog').close();toast(SbandT("Добавлено в корзину"));await loadMarket();}catch(e){error(e);}};
      $('#share-product').onclick=()=>{
        const url='https://t.me/'+state.me.bot_username+'?start=product_'+id;
        const share='https://t.me/share/url?url='+encodeURIComponent(url)+'&text='+encodeURIComponent(item.name+' · '+rub(item.price));
        if(tg?.openTelegramLink) tg.openTelegramLink(share);else window.open(share,'_blank','noopener,noreferrer');
      };
    }catch(e){error(e);}
  }
  function knowledge() {
    modal(SbandT("<h2 id=\"dialog-title\">Помощь и инструкции</h2><input id=\"knowledge-search\" type=\"search\" placeholder=\"Найти ответ\" aria-label=\"Поиск инструкции\"><div id=\"knowledge-results\"></div><p>{0}. {1}</p><button class=\"primary-button\" data-bot>Написать поддержке / отправить скриншот</button>",esc(state.support?.support_hours),esc(state.support?.response_time)));
    const entries=[[SbandT("Как купить?"),SbandT("Добавьте аккаунты в корзину. Резерв длится 5 минут. Пополните баланс и подтвердите сумму.")],[SbandT("Как войти?"),SbandT("Откройте покупку, введите номер в Telegram. Код получите в боте. Если указан пароль 2FA, используйте его, затем смените пароль и привяжите почту.")],[SbandT("Гарантия и замена"),SbandT("Срок указан в заказе. Отправьте гарантийную заявку до его окончания. Поддержка проверит проблему и решит вопрос возврата или замены.")],[SbandT("Как отправить скриншот?"),SbandT("В боте откройте обращение по заказу, нажмите Ответить и отправьте фото. Не отправляйте пароли и коды входа.")],[SbandT("Оптовая скидка"),SbandT("Применяется автоматически от ")+rub(state.wholesale.minimum)+': '+state.wholesale.percent+SbandT("%. Промокод применяется после неё.")],[SbandT("Оплата не появилась"),SbandT("Проверка идёт автоматически. Сохраните номер счёта, проверьте статус в платёжном сервисе. При задержке обратитесь в поддержку.")]];
    const render=()=>{const q=$('#knowledge-search').value.toLowerCase();$('#knowledge-results').innerHTML=entries.filter(e=>e.join(' ').toLowerCase().includes(q)).map(e=>`<details class="help-article"><summary>${esc(e[0])}</summary><p>${esc(e[1])}</p></details>`).join('') || SbandT("<p>Ответ не найден. Напишите поддержке.</p>");};
    $('#knowledge-search').oninput=render;render();
  }
  function reviewEditor(order) {
    modal(SbandT("<h2 id=\"dialog-title\">Отзыв о покупке</h2><p>Публикуется без имени и Telegram ID. Не указывай номер, пароль или коды входа. Один отзыв на заказ, его можно изменить.</p><label for=\"review-rating\">Оценка</label><select id=\"review-rating\">{0}</select><label for=\"review-body\">Отзыв</label><textarea id=\"review-body\" maxlength=\"500\" rows=\"4\">{1}</textarea><p id=\"dialog-error\" class=\"dialog-error\" hidden></p><button id=\"save-review\" class=\"primary-button\">Опубликовать отзыв</button>",[5,4,3,2,1].map(r=>SbandT("<option value=\"{0}\" {1}>{2} из 5</option>",r,Number(order.review?.rating) === r ? 'selected' : '',r)).join(''),esc(order.review?.body || '')));
    $('#save-review').onclick = async () => {
      if (state.busy) return; state.busy = true; $('#save-review').disabled = true;
      try { await post('reviews',{purchase_id:order.id,rating:Number($('#review-rating').value),body:$('#review-body').value}); $('#purchase-dialog').close(); toast(SbandT("Отзыв опубликован")); }
      catch(e) { dialogError(e); if($('#save-review')) $('#save-review').disabled = false; }
      finally { state.busy = false; }
    };
  }
  function warrantyEditor(order) {
    modal(SbandT("<h2 id=\"dialog-title\">Гарантийное обращение</h2><p>Опиши проблему со входом. Не отправляй пароль, код или сессию. Срок проверяется при отправке; обращение сохраняется в поддержке бота.</p><label for=\"claim-body\">Что произошло?</label><textarea id=\"claim-body\" maxlength=\"500\" rows=\"4\"></textarea><p id=\"dialog-error\" class=\"dialog-error\" hidden></p><button id=\"send-claim\" class=\"primary-button\">Отправить обращение</button>"));
    $('#send-claim').onclick = async () => {
      if (state.busy) return; state.busy = true; $('#send-claim').disabled = true;
      try { const result = await post('orders/'+order.id+'/warranty-claim',{body:$('#claim-body').value}); modal(SbandT("<h2 id=\"dialog-title\">Обращение #{0}</h2><p>Сохранено. Поддержка ответит в Telegram-боте.</p><button class=\"primary-button\" data-bot-order=\"{1}\">Открыть в боте</button>",result.ticket_id,order.id)); }
      catch(e) { dialogError(e); if($('#send-claim')) $('#send-claim').disabled = false; }
      finally { state.busy = false; }
    };
  }
  async function showReviews(page = 0) {
    const dialogRevision = ++state.dialogRevision;
    try {
      const data = await api('reviews?page='+page);
      if (dialogRevision !== state.dialogRevision) return;
      modal(SbandT("<h2 id=\"dialog-title\">Отзывы покупателей</h2><p>Средняя оценка: {0} / 5 · Отзывов: {1}</p>{2}{3}{4}",data.average == null ? '—' : num(data.average),data.count,data.items.map(r=>SbandT("<article class=\"review\"><b>{0} / 5 · Покупатель</b><p>{1}</p><small>Подтверждённая покупка</small></article>",Number(r.rating),esc(r.body))).join('') || SbandT("<p>Отзывов пока нет. Оставить свой можно в деталях покупки.</p>"),page ? SbandT("<button id=\"previous-reviews\" class=\"secondary-button\">Предыдущие</button>") : '',data.has_more ? SbandT("<button id=\"next-reviews\" class=\"secondary-button\">Следующие</button>") : ''));
      if($('#previous-reviews')) $('#previous-reviews').onclick = () => showReviews(page-1);
      if($('#next-reviews')) $('#next-reviews').onclick = () => showReviews(page+1);
    } catch(e) { error(e); }
  }
  function balancePromo() {
    if(!state.ready) return;
    modal(SbandT("<h2 id=\"dialog-title\">Промокод на баланс</h2><label for=\"balance-code\">Промокод</label><input id=\"balance-code\" maxlength=\"64\"><p id=\"balance-preview\"></p><p id=\"dialog-error\" class=\"dialog-error\" hidden></p><button id=\"check-balance-code\" class=\"secondary-button\">Проверить</button><button id=\"redeem-balance-code\" class=\"primary-button\" hidden>Активировать</button>"));
    let checked = null;
    $('#balance-code').oninput = () => { checked = null; $('#redeem-balance-code').hidden = true; $('#balance-preview').textContent = ''; };
    $('#check-balance-code').onclick = async () => {
      const btn = $('#check-balance-code'); btn.disabled = true; checked = null; $('#redeem-balance-code').hidden = true; $('#dialog-error').hidden = true;
      const typed = $('#balance-code').value;
      try { const r = await post('promo/preview',{code:typed}); if (!btn.isConnected || $('#balance-code').value !== typed) return; checked = r; $('#balance-preview').textContent = r.kind === 'balance' ? SbandT("На баланс будет зачислено ")+rub(r.value) : SbandT("Скидка ")+num(r.value)+SbandT("%. Применяется в окне оплаты корзины."); $('#redeem-balance-code').hidden = r.kind !== 'balance'; }
      catch(e) { dialogError(e); } finally { btn.disabled = false; }
    };
    $('#redeem-balance-code').onclick = async () => {
      if(!checked || state.busy) return; state.busy = true; $('#redeem-balance-code').disabled = true;
      try { const r = await post('promo/redeem',{code:checked.code}); $('#purchase-dialog').close(); await loadMe(); toast(SbandT("На баланс зачислено ")+rub(r.credited)); }
      catch(e) { dialogError(e); if($('#redeem-balance-code')) $('#redeem-balance-code').disabled = false; } finally { state.busy = false; }
    };
  }
  async function wheel() {
    if(!state.ready || state.busy) return;
    try {
      const d=await api('rewards');
      modal(SbandT("<h2 id=\"dialog-title\">Колесо удачи</h2><p>Случайный бонус от 1 до 10 ₽ на баланс. Шанс каждой целой суммы — 10%.</p><p>Пополнения в сумме от 50 ₽ за последние 72 часа. Получение раз в 3 дня. Промокоды, подарки и возвращённые Stars не учитываются.</p><p>Подходящие пополнения: {0}.</p>{1}<p id=\"dialog-error\" hidden></p><button id=\"claim-wheel\" class=\"primary-button\" {2}>Крутить колесо</button>",rub(d.paid),d.next_at ? SbandT("<p>Следующий интервал: {0} МСК</p>",esc(new Date(d.next_at).toLocaleString(window.SbandI18n.locale,{timeZone:'Europe/Moscow'}))) : '',d.eligible?'':'disabled'));
      $('#claim-wheel').onclick=async()=>{
        if(state.busy) return;state.busy=true;$('#claim-wheel').disabled=true;
        try {const r=await post('rewards/claim',{});modal(SbandT("<h2 id=\"dialog-title\">Ваш бонус: {0}</h2><p>Уже зачислен на баланс. Следующее получение — через 3 дня при выполнении условия пополнения.</p>",rub(r.amount)));await loadMe();}
        catch(e){dialogError(e);}finally{state.busy=false;}
      };
    }catch(e){error(e);}
  }
  async function topup() {
    const dialogRevision = ++state.dialogRevision;
    if (!state.ready || state.busy) return;
    if (state.invoice) { showInvoice(); return; }
    try {
      const data = await api('payment-methods'), methods = data.items.filter(m => m.enabled);
      if (dialogRevision !== state.dialogRevision) return;
      if (!methods.length) { modal(SbandT("<h2 id=\"dialog-title\">Пополнение баланса</h2><p>Платёжные сервисы пока не настроены. Обратись к администратору через Telegram-бота.</p><button class=\"primary-button\" data-bot>Открыть бота <svg class=\"arrow\" viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M6 18 18 6M6 6h12v12\"/></svg></button>")); return; }
      modal(SbandT("<h2 id=\"dialog-title\">Пополнить баланс</h2><p>Баланс обновится после подтверждения оплаты.</p><label for=\"topup-method\">Способ оплаты</label><select id=\"topup-method\">{0}</select><label for=\"topup-amount\" id=\"topup-amount-label\">Сумма, ₽</label><input id=\"topup-amount\" type=\"number\" inputmode=\"decimal\" min=\"10\" max=\"1000000\" step=\"0.01\" value=\"500\"><p id=\"topup-quote\" class=\"muted\" aria-live=\"polite\"></p><p id=\"dialog-error\" class=\"dialog-error\" role=\"alert\" hidden></p><button class=\"primary-button\" id=\"create-invoice\">Создать счёт <svg class=\"arrow\" viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M6 18 18 6M6 6h12v12\"/></svg></button>",methods.map(m => `<option value="${esc(m.id)}">${esc(m.name)}</option>`).join('')));
      const amountInput = $('#topup-amount'), methodInput = $('#topup-method'), createButton = $('#create-invoice');
      const remembered = { rub: '500', stars: '100' };
      let currentUnit = null;
      const selectedMethod = () => methods.find(method=>method.id===methodInput.value);
      const starCount = () => /^[0-9]{1,5}$/.test(amountInput.value) && Number(amountInput.value) >= 1 && Number(amountInput.value) <= Number(selectedMethod().max);
      const updateQuote = () => {
        const stars = methodInput.value === 'stars', unit = stars ? 'stars' : 'rub';
        if (currentUnit !== unit) {
          if (currentUnit) remembered[currentUnit] = amountInput.value;
          amountInput.value = remembered[unit]; currentUnit = unit;
        }
        $('#topup-amount-label').textContent = stars ? SbandT("Количество звёзд, ⭐") : SbandT("Сумма, ₽");
        amountInput.min = String(selectedMethod().min); amountInput.max = String(selectedMethod().max); amountInput.step = stars ? '1' : '0.01'; amountInput.inputMode = stars ? 'numeric' : 'decimal';
        const valid = stars ? starCount() : amountInput.checkValidity() && Number(amountInput.value) >= Number(amountInput.min) && Number(amountInput.value) <= Number(amountInput.max);
        $('#topup-quote').textContent = stars ? (valid ? SbandT("{0} ⭐ → {1} ₽ на баланс. Курс: 1 ⭐ = 1,20 ₽.",num(amountInput.value),Number(amountInput.value * 120 / 100).toLocaleString(window.SbandI18n.locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 })) : SbandT("Введите целое число от 1 до 10 000 ⭐.")) : SbandT('Сумма пополнения: от {0} до {1} ₽.',num(amountInput.min),num(amountInput.max));
        createButton.textContent = methodInput.value === 'platega' ? SbandT('Оплатить {0} ₽',num(amountInput.value)) : SbandT('Создать счёт');
        createButton.disabled = state.busy || !valid;
      };
      methodInput.onchange = updateQuote; amountInput.oninput = updateQuote; updateQuote();
      createButton.onclick = async () => {
        if (state.busy || !amountInput.checkValidity() || (methodInput.value === 'stars' && !starCount())) return;
        const provider = methodInput.value;
        const body = provider === 'stars' ? { provider, stars: Number(amountInput.value) } : { provider, amount: amountInput.value };
        const revision = state.dialogRevision;
        state.busy = true; createButton.disabled = true; amountInput.disabled = true; methodInput.disabled = true;
        try {
          state.invoice = await post('invoices', body);
          if (revision === state.dialogRevision) showInvoice();
        } catch (e) { dialogError(e); }
        finally { state.busy = false; if (createButton.isConnected) { amountInput.disabled = false; methodInput.disabled = false; updateQuote(); } }
      };
    } catch (e) { error(e); }
  }
  function showInvoice() {
    const i = state.invoice; if (!i) return;
    let url;
    try { url = new URL(i.pay_url); } catch (_) { state.invoice = null; throw new Error(SbandT("Не удалось открыть ссылку счёта. Создай новый счёт.")); }
    const stars = i.provider === 'stars';
    if (url.protocol !== 'https:' || url.username || url.password || (stars && (!['t.me', 'telegram.me'].includes(url.hostname) || !Number.isInteger(i.stars) || i.stars < 1 || i.stars > 10000 || Math.round(Number(i.amount) * 100) !== i.stars * 120))) {
      state.invoice = null; throw new Error(SbandT("Счёт содержит некорректные условия оплаты. Создай новый счёт."));
    }
    const nativeStars = stars && typeof tg?.openInvoice === 'function';
    const paymentControl = nativeStars ? SbandT("<button id=\"pay-stars\" class=\"primary-button\">Оплатить {0} ⭐</button><a id=\"stars-payment-link\" class=\"payment-link\" href=\"{1}\" target=\"_blank\" rel=\"noopener noreferrer\" hidden>Открыть счёт в Telegram</a>",num(i.stars),esc(url.href)) : `<a class="payment-link" href="${esc(url.href)}" target="_blank" rel="noopener noreferrer">${stars ? SbandT("Оплатить {0} ⭐ в Telegram",num(i.stars)) : SbandT("Перейти к оплате")} <svg class="arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 18 18 6M6 6h12v12"/></svg></a>`;
    modal(SbandT("<h2 id=\"dialog-title\">{0}</h2>{1}{2}<p id=\"invoice-state\" role=\"status\">Ожидаем оплату…</p><p id=\"dialog-error\" class=\"dialog-error\" role=\"alert\" hidden></p>{3}<p>Можно закрыть это окно: проверка продолжится на сервере.</p><button id=\"another-invoice\" class=\"secondary-button\">Создать другой счёт</button>",stars ? SbandT("Счёт на {0} ⭐",num(i.stars)) : SbandT("Счёт на {0}",rub(i.amount)),stars ? SbandT("<div class=\"info\"><span>На баланс</span><b>{0}</b></div><p>Курс: 1 ⭐ = 1,20 ₽. Зачисление произойдёт после подтверждения оплаты Telegram.</p>",rub(i.amount)) : SbandT("<p>Перейди к оплате. Баланс обновится автоматически после подтверждения платёжным сервисом.</p>"),paymentControl,stars ? SbandT("<button id=\"verify-invoice\" class=\"secondary-button\">Проверить зачисление</button>") : ''));
    if (nativeStars) {
      const button = $('#pay-stars');
      button.onclick = () => {
        if (button.disabled || state.invoice !== i) return;
        button.disabled = true;
        try {
          tg.openInvoice(url.href, async status => {
            if (state.invoice !== i) return;
            button.disabled = false;
            const label = $('#invoice-state');
            if (label) label.textContent = status === 'paid' || status === 'pending' ? SbandT("Проверяем подтверждение оплаты Telegram…") : status === 'cancelled' ? SbandT("Оплата отменена. Можно открыть счёт снова.") : SbandT("Оплата не завершена. Проверь статус счёта или попробуй снова.");
            if (status === 'paid' || status === 'pending') {
              try { await checkInvoice(); await loadMe(); } catch (e) { dialogError(e); }
            }
          });
        } catch (_) {
          button.disabled = false;
          $('#stars-payment-link').hidden = false;
          $('#invoice-state').textContent = SbandT("Не удалось открыть оплату в приложении. Воспользуйся ссылкой на счёт в Telegram.");
        }
      };
    }
    if ($('#verify-invoice')) $('#verify-invoice').onclick = async () => {
      const button = $('#verify-invoice'); button.disabled = true;
      try { await checkInvoice(); await loadMe(); } catch (e) { dialogError(e); }
      finally { if (button.isConnected && state.invoice === i) button.disabled = false; }
    };
    $('#another-invoice').onclick = () => { state.invoice = null; topup(); };
  }
  async function checkInvoice() {
    const i = state.invoice; if (!i) return;
    const data = await api('invoices/' + encodeURIComponent(i.provider) + '/' + encodeURIComponent(i.invoice_id));
    if (state.invoice !== i) return;
    if (data.status === 'credited' || data.status === 'refunded') {
      state.invoice = null; await loadMe();
      if ($('#invoice-state')) $('#invoice-state').textContent = data.status === 'credited' ? SbandT("✓ Оплата подтверждена. Баланс пополнен!") : SbandT("Платёж возвращён. Баланс обновлён.");
      if ($('#pay-stars')) $('#pay-stars').disabled = true;
      if ($('#verify-invoice')) $('#verify-invoice').disabled = true;
      toast(data.status === 'credited' ? SbandT("Баланс пополнен автоматически") : SbandT("Возврат платежа подтверждён"));
    } else if (data.status === 'expired') {
      state.invoice = null;
      if ($('#invoice-state')) $('#invoice-state').textContent = SbandT("Срок счёта истёк. Создай новый счёт.");
      if ($('#pay-stars')) $('#pay-stars').disabled = true;
      if ($('#verify-invoice')) $('#verify-invoice').disabled = true;
    }
  }
  async function showReferrals() {
    const revision = ++state.dialogRevision;
    try {
      const data = await api('referrals');
      if (revision !== state.dialogRevision) return;
      const s = data.settings;
      const username = /^[A-Za-z0-9_]{5,32}$/.test(data.bot_username || '') ? data.bot_username : null;
      const link = username ? 'https://t.me/' + username + '?start=ref_' + state.me.user.id : '';
      modal(SbandT('<h2 id="dialog-title">Реферальная программа</h2><p>Приглашай новых пользователей по своей ссылке. Награды поступают на твой баланс.</p><div class="info"><span>За нового реферала</span><b>{0}</b></div><div class="info"><span>С его пополнений</span><b>{1}%</b></div><div class="info"><span>С его покупок</span><b>{2}%</b></div><div class="info"><span>Скидка приглашённому</span><b>{3}%</b></div><div class="info"><span>Приглашено</span><b>{4}</b></div><div class="info"><span>Начислено с учётом возвратов</span><b>{5}</b></div><p>Проценты начисляются от фактически оплаченной суммы, без бонусных зачислений. При возврате оплаты соответствующая награда отменяется.</p><label for="referral-link">Твоя ссылка</label><input id="referral-link" readonly value="{6}"><button id="copy-referral" class="primary-button">Скопировать ссылку</button>',rub(s.signup_bonus),num(s.deposit_pct),num(s.bonus_pct),num(s.discount_pct),data.count,rub(data.earned),esc(link)));
      const daily = data.daily;
      const rows = items => items.map(item=>'<div class="info referral-person"><span>'+esc(item.username?'@'+item.username:SbandT('Пользователь'))+'</span><code>'+esc(item.id)+'</code></div>').join('');
      $('#dialog-content').insertAdjacentHTML('beforeend',SbandT('<h3>Дневной лимит</h3><p>По Москве: {0}. Начислено сегодня: {1}. Осталось: {2}.</p><p>Фактическая награда ограничена дневным остатком. Возвраты не восстанавливают лимит.</p>',rub(daily.limit),rub(daily.issued),rub(daily.remaining))+(daily.blocked?SbandT('<p class="dialog-error">Реферальные начисления заблокированы администратором.</p>'):'')+SbandT('<h3>Мои рефералы</h3><div id="referral-users">{0}</div><button class="secondary-button" id="more-referral-users">Ещё рефералы</button>',rows(data.items)||SbandT('Рефералов пока нет.')));
      let referralPage = 0;
      $('#more-referral-users').hidden = !data.has_more;
      $('#more-referral-users').onclick = async () => { const button=$('#more-referral-users'),list=$('#referral-users');button.disabled=true;try{const next=await api('referrals?page='+(referralPage+1));if(!list.isConnected)return;referralPage++;list.insertAdjacentHTML('beforeend',rows(next.items));button.hidden=!next.has_more;}catch(e){if(list.isConnected)toast(e.message);}finally{button.disabled=false;} };
      $('#copy-referral').disabled = !link;
      $('#copy-referral').onclick = async () => {
        try { await navigator.clipboard.writeText(link); toast(SbandT('Ссылка скопирована')); }
        catch (_) { $('#referral-link').focus(); $('#referral-link').select(); toast(SbandT('Выдели и скопируй ссылку')); }
      };
    } catch (e) { error(e); }
  }
  let spamRefreshing = false;
  async function refreshSpam() {
    if (!state.ready || state.busy || state.refreshing || spamRefreshing || document.hidden || $('#purchase-dialog').open || document.body.classList.contains('admin-mode') || !['catalog','favorites','cart'].includes(state.tab)) return;
    const visible = [...document.querySelectorAll('[data-spam-status]')].filter(el => { const b = el.getBoundingClientRect(); return b.bottom > 0 && b.top < innerHeight; }).slice(0,50);
    if (!visible.length) return;
    const revision = state.revision;
    spamRefreshing = true;
    try {
      const data = await api('spam-status?ids=' + visible.map(el=>el.dataset.spamStatus).join(','));
      if (!state.ready || state.busy || state.refreshing || revision !== state.revision || $('#purchase-dialog').open) return;
      const checks = new Map(data.items.map(item=>[item.id,item]));
      for (const el of visible) {
        if (!el.isConnected) continue;
        const item = state.items.find(item=>item.id===Number(el.dataset.spamStatus)), update = checks.get(Number(el.dataset.spamStatus));
        if (!item) continue;
        item.available = !!update?.available;
        if (update) {
          item.characteristics = {...item.characteristics,spam_check:update.spam_check};
          el.textContent = SbandT('Спамблок: ') + spamLabel(update.spam_check);
          el.title = spamTime(update.spam_check);
          el.classList.toggle('spam-limited',['limited','permanent'].includes(update.spam_check.status));
          el.classList.toggle('spam-clear',update.spam_check.status==='clear'&&!update.spam_check.running);
        }
        const card = el.closest('.account-card'), buy = card.querySelector('[data-add]'), stock = card.querySelector('.stock-tag');
        buy.disabled = !item.available || !!state.me?.shop_status?.sales_paused;
        stock.textContent = item.available ? SbandT('В наличии') : SbandT('Недоступен');
        stock.classList.toggle('unavailable',!item.available);
      }
      countdown();
    } catch (_) { /* Retain the last verified result; a network error is never a clear status. */ }
    finally { spamRefreshing = false; }
  }
  async function synchronize() {
    if (!state.ready || state.busy || state.refreshing || document.hidden || document.body.classList.contains('admin-mode')) return;
    state.refreshing = true;
    try { await Promise.all([loadMe(), state.tab === 'messages' ? refreshSupport() : state.tab === 'orders' ? (state.orderPage === 0 ? loadOrders() : null) : (state.page === 0 ? loadMarket() : null), checkInvoice()]); $('#sync-state').textContent = (state.tab === 'orders' ? state.orderPage : state.page) > 0 ? SbandT("● Баланс обновлён") : SbandT("● Обновлено сейчас"); }
    catch(e) { if(e.code==='maintenance'){showMaintenance(e.details?.shop_status);return;} $('#sync-state').textContent=SbandT("Нет обновления"); if(e.code==='unauthorized') reset(e.message); }
    finally { state.refreshing=false; }
  }
  async function initialize() {
    try { await window.SbandI18n.ready; tg?.ready(); tg?.expand(); tg?.setHeaderColor('#101116'); tg?.setBackgroundColor('#1c1d24'); await loadMe(); const info=await api('shop-info');state.wholesale=info.wholesale;state.support=info; state.ready = true; document.body.classList.remove('maintenance-mode'); $('#maintenance-page').hidden=true; $('#login-panel').hidden = true; notice(); showPage(); if(state.tab==='messages')await loadSupport();else await loadMarket(); $('#sync-state').textContent = SbandT("● Обновлено сейчас"); const start=tg?.initDataUnsafe?.start_param || new URLSearchParams(location.search).get('tgWebAppStartParam') || (new URLSearchParams(location.search).get('product') ? 'product_'+new URLSearchParams(location.search).get('product') : ''); if(/^product_[0-9]{1,10}$/.test(start)) await features(Number(start.slice(8))); }
    catch (e) { if(e.code==='maintenance')showMaintenance(e.details?.shop_status);else reset(e.message); }
  }
  document.addEventListener('sband-shop',()=>{if(state.ready) { showPage(); synchronize(); }});
  document.addEventListener('sband-auth-error',()=>reset(SbandT("Открой приложение заново через Telegram.")));
  document.addEventListener('click', async event => {
    const button = event.target.closest('button'); if (!button || button.disabled) return;
    if(button.dataset.language) {state.meRevision=(state.meRevision||0)+1;button.disabled=true;try{await post('preferences/language',{language:button.dataset.language});await initialize();}catch(e){error(e);}finally{button.disabled=false;}return;}
    if(button.id==='check-maintenance') {button.disabled=true;try{const data=await api('status');if(data.shop_status.maintenance){showMaintenance(data.shop_status);$('#maintenance-feedback').textContent=SbandT("🛠 Работы ещё продолжаются. Статус обновлён.");}else{await initialize();}}catch(e){$('#maintenance-feedback').textContent=e.message;}finally{button.disabled=false;}return;}
    if(button.hasAttribute('data-demo')) { if(state.me?.is_admin){sessionStorage.setItem('sband_test_init',tg?.initData||'');location.assign('/demo'+location.hash);}return; }
    if(button.hasAttribute('data-demo-exit')) { try{await post('demo/exit',{});await loadMe();notice(SbandT("Тестовый режим закрыт. Рабочие операции доступны."));}catch(e){error(e);}return; }
    if(button.hasAttribute('data-header-search')){await switchTab('home');$('#home-query').focus();return;}
    if(button.hasAttribute('data-discover')){state.category='';$('#search').value=button.dataset.discover;switchTab('catalog');return;}
    if(button.dataset.department){openDepartment(button.dataset.department);return;}
    if(button.dataset.supportTicket){openSupport(Number(button.dataset.supportTicket));return;}
    if (button.dataset.tab) { switchTab(button.dataset.tab); return; }
    if (button.hasAttribute('data-bot')) openBot();
    if (button.dataset.botOrder) openBot(Number(button.dataset.botOrder));
    if (button.dataset.features) features(Number(button.dataset.features));
    if (button.hasAttribute('data-knowledge')) knowledge();
    if (button.hasAttribute('data-reviews')) showReviews();
    if (button.hasAttribute('data-balance-promo')) balancePromo();
    if (button.hasAttribute('data-wheel')) wheel();
    if (button.hasAttribute('data-referrals')) showReferrals();
    if (button.dataset.order) showOrder(Number(button.dataset.order));
    if (button.hasAttribute('data-topup')) topup();
    if (button.hasAttribute('data-category')) { state.category=button.dataset.category; if(state.tab==='home')switchTab('catalog');else loadMarket().catch(error); }
    if (button.dataset.add || button.dataset.favorite || button.dataset.remove) {
      const id = Number(button.dataset.add || button.dataset.favorite || button.dataset.remove), item = state.items.find(i => i.id === id); if (!item) return;
      button.disabled = true;
      try {
        if (button.dataset.add) { await post('cart', { account_id: id }); toast(item.in_cart ? SbandT("Резерв проверен") : SbandT("В корзине · резерв на 5 минут")); }
        else if (button.dataset.remove) await post('cart', { account_id: id }, 'DELETE');
        else { await post('favorites', { account_id: id, enabled: !item.favorite }); toast(item.favorite ? SbandT("Удалено из избранного") : SbandT("Сохранено · о снижении цены сообщим в боте")); }
        await loadMarket();
      } catch (e) { error(e); button.disabled = false; }
    }
  });
  $('#countries-toggle').onclick = e => {
    const expanded=$('#categories').classList.toggle('expanded');
    e.currentTarget.setAttribute('aria-expanded',String(expanded));
    e.currentTarget.textContent=SbandT(expanded?'Свернуть страны ↑':'Все страны ↓');
  };
  $('#home-search').onsubmit=e=>{e.preventDefault();state.category='';$('#search').value=$('#home-query').value;switchTab('catalog');};
  $('#open-filters').onclick=()=>{const panel=$('.filter-panel');panel.open=!panel.open;if(panel.open)$('#search').focus();};
  $('#stock-countries').onclick=()=>{state.onlyStockCountries=true;$('#stock-countries').setAttribute('aria-pressed','true');$('#all-countries').setAttribute('aria-pressed','false');renderDiscovery();};
  $('#all-countries').onclick=()=>{state.onlyStockCountries=false;$('#stock-countries').setAttribute('aria-pressed','false');$('#all-countries').setAttribute('aria-pressed','true');renderDiscovery();};
  $('#support-new').onsubmit=async e=>{
    e.preventDefault();const button=e.currentTarget.querySelector('button');button.disabled=true;$('#support-error').hidden=true;$('#support-success').hidden=true;
    try{const data=await post('support',{body:$('#support-body').value});$('#support-body').value='';$('#support-success').hidden=false;await loadSupport();await openSupport(data.ticket_id);}catch(e){$('#support-error').textContent=e.message;$('#support-error').hidden=false;}finally{button.disabled=false;}
  };
  $('#refresh-support').onclick=()=>loadSupport().catch(error);
  $('#support-more').onclick=async()=>{const b=$('#support-more');b.disabled=true;try{await loadSupport(true);}catch(e){error(e);}finally{b.disabled=false;}};
  $('#checkout-cart').onclick = checkout;
  $('#close-dialog').onclick = () => { if (!state.busy) $('#purchase-dialog').close(); };
  $('#purchase-dialog').addEventListener('cancel', e => { if (state.busy) e.preventDefault(); });
  $('#purchase-dialog').addEventListener('close', () => { if (!$('#purchase-dialog').open) { state.dialogRevision++; $('#dialog-content').replaceChildren(); } });
  for (const id of ['search', 'min-price', 'max-price']) $('#' + id).addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { if (state.ready) loadMarket().catch(error); }, 300); });
  $('#sort').onchange = () => loadMarket().catch(error);
  for(const id of ['premium-filter','age-filter']) $('#'+id).onchange=()=>loadMarket().catch(error);
  $('#order-search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>loadOrders().catch(error),300);};
  $('#load-more').onclick = async () => { $('#load-more').disabled = true; try { await loadMarket(true); } catch (e) { error(e); } finally { $('#load-more').disabled = false; } };
  $('#more-orders').onclick = async () => { $('#more-orders').disabled = true; try { await loadOrders(true); } catch (e) { error(e); } finally { $('#more-orders').disabled = false; } };
  $('#refresh').onclick = () => loadMarket().then(() => notice()).catch(error); $('#refresh-orders').onclick = () => loadOrders().catch(error); $('#retry-login').onclick = initialize;
  document.addEventListener('visibilitychange', () => { if (!document.hidden) synchronize(); }); window.addEventListener('online', synchronize);
  window.addEventListener('offline', () => notice(SbandT("Нет соединения. Подключись к интернету, чтобы обновить данные.")));
  setInterval(countdown, 1000); setInterval(synchronize, 15000); setInterval(refreshSpam, 5000); initialize();
})();
